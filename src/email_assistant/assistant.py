import os
from typing import Literal

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from pydantic import SecretStr

from email_assistant.schemas import RouterSchema, State
from email_assistant.tools.default.email_tools import Done, Question, triage_email, write_email
from email_assistant.tools.default.prompt_tools import HITL_TOOLS_PROMPT
from email_assistant.prompts import triage_user_prompt, triage_system_prompt, default_triage_instructions, assistant_system_prompt_hitl, default_background, default_response_preferences
from email_assistant.utils import format_email_markdown, format_toolcall_display, parse_email

############################################################################
# Initialize environment variables
############################################################################
load_dotenv()  # Load environment variables from .env file

api_key = os.getenv('ARK_API_KEY')
if not api_key:
    raise ValueError("ARK_API_KEY environment variable is not set.")

############################################################################
# Initialize LLMs
############################################################################

# Collect the tools
tools = [write_email, triage_email, Done, Question]
tools_by_name = {tool.name: tool for tool in tools}

# Initialize the LLM with tools
llm = init_chat_model(model="glm-4-7-251222",
                model_provider="openai",
                base_url='https://ark.cn-beijing.volces.com/api/v3',
                api_key=SecretStr(api_key),
                temperature=0)  # Initialize the chat model
llm_with_tools = llm.bind_tools(tools, tool_choice="any")

# Initialize the LLM for structured output
structured_llm = init_chat_model(model="doubao-seed-1-8-251228",
                model_provider="openai",
                base_url='https://ark.cn-beijing.volces.com/api/v3',
                api_key=SecretStr(api_key),
                temperature=0)
llm_router = structured_llm.with_structured_output(RouterSchema) # Initialize the chat model

############################################################################
# Define response agent graph
############################################################################
def llm_call(state: State):
    """
    LLM decides whether to call a tool or not.

    Args:
        state (State): The current state of the conversation.

    Returns:
        str: The response from the language model.
    """

    return {
        "messages":[
            # Invoke the LLM
            llm_with_tools.invoke(
                # System prompt is here
                [
                    {"role": "system",
                     "content": assistant_system_prompt_hitl.format(
                         tools_prompt=HITL_TOOLS_PROMPT,
                         background=default_background,
                         response_preferences=default_response_preferences
                    )}
                ]
                # Add messages from the state
                + state["messages"]
            )
        ]
    }

def tool_handler(state: State):
    """
    Handle tool calls and update the state accordingly.

    Args:
        state (State): The current state of the conversation.
    """

    # List for tool messages
    result = []

    # Iterate through tool calls
    for tool_call in state["messages"][-1].tool_calls:
        # Get the tool
        tool = tools_by_name[tool_call["name"]]
        # Run it
        observation = tool.invoke(tool_call["args"])
        # Create a tool message
        result.append({"role": "tool", "content" : observation, "tool_call_id": tool_call["id"]})

    # Add it to our messages
    return {"messages": result}

def response_interrupt_handler(state: State) -> Command[Literal["llm_call", "__end__"]]:
    """Creates an interrupt for human review of tool calls"""

    # Store messages
    result = []

    # Go to the LLM call node
    goto = "llm_call"

    # Iterate over tool calls
    for tool_call in state["messages"][-1].tool_calls:

        # Allowed tools for HITL review
        hitl_tools = ["write_email", "Question"]

        # If tool is not in our HITL list, execute it directly without interruption
        if tool_call["name"] not in hitl_tools:
            # Execute tool without interruption
            tool = tools_by_name[tool_call["name"]]
            observation = tool.invoke(tool_call["args"])
            result.append({"role": "tool", "content": observation, "tool_call_id": tool_call["id"]})
            continue

        # Get original email
        email_input = state["email_input"]
        author, to, subject, email_thread = parse_email(email_input)
        original_email_markdown = format_email_markdown(subject, author, to, email_thread)

        # Format tool call for display and prepend the original email
        tool_display = format_toolcall_display(tool_call)
        description = original_email_markdown + tool_display

        # Configure what actions are allowed in Agent Inbox
        if tool_call["name"] == "write_email":
            config = {
                "allow_ignore": True,
                "allow_response": True,
                "allow_edit": True,
                "allow_accept": True,
            }
        elif tool_call["name"] == "schedule_meeting":
            config = {
                "allow_ignore": True,
                "allow_response": True,
                "allow_edit": True,
                "allow_accept": True,
            }
        elif tool_call["name"] == "Question":
            config = {
                "allow_ignore": True,
                "allow_response": True,
                "allow_edit": False,
                "allow_accept": False,
            }
        else:
            raise ValueError(f"Invalid tool call: {tool_call['name']}")

        # Create the interrupt request
        request = {
            "action_request": {
                "action": tool_call["name"],
                "args": tool_call["args"]
            },
            "config": config,
            "description": description,
        }

        # Send to Agent Inbox and wait for response
        response = interrupt([request])[0]

        # Handle the response from Agent Inbox
        if response["type"] == "accept":

            # Execute the tool with the original args
            tool = tools_by_name[tool_call["name"]]
            observation = tool.invoke(tool_call["args"])
            result.append({"role": "tool", "content": observation, "tool_call_id": tool_call["id"]})

        elif response["type"] == "edit":

            # Tool selection
            tool = tools_by_name[tool_call["name"]]

            # Get edited args from Agent Inbox
            edited_args = response["args"]["args"]

            # Update the AI message's tool call with edited content (reference to the message in the state)
            ai_message = state["messages"][-1] # Get the most recent message from the state
            current_id = tool_call["id"] # Store the ID of the tool call being edited

            # Create a new list of tool calls by filtering out the one being edited and adding the updated version
            # This avoids modifying the original list directly (immutable approach)
            updated_tool_calls = [tc for tc in ai_message.tool_calls if tc["id"] != current_id] + [
                {"type": "tool_call", "name": tool_call["name"], "args": edited_args, "id": current_id}
            ]

            # Create a new copy of the message with updated tool calls rather than modifying the original
            # This ensures state immutability and prevents side effects in other parts of the code
            # When we update the messages state key ("messages": result), the add_messages reducer will
            # overwrite existing messages by id and we take advantage of this here to update the tool calls.
            result.append(ai_message.model_copy(update={"tool_calls": updated_tool_calls}))

            # Update the write_email tool call with the edited content from Agent Inbox
            if tool_call["name"] == "write_email":

                # Execute the tool with edited args
                observation = tool.invoke(edited_args)

                # Add only the tool response message
                result.append({"role": "tool", "content": observation, "tool_call_id": current_id})


            # Update the schedule_meeting tool call with the edited content from Agent Inbox
            elif tool_call["name"] == "schedule_meeting":


                # Execute the tool with edited args
                observation = tool.invoke(edited_args)

                # Add only the tool response message
                result.append({"role": "tool", "content": observation, "tool_call_id": current_id})

            # Catch all other tool calls
            else:
                raise ValueError(f"Invalid tool call: {tool_call['name']}")

        elif response["type"] == "ignore":
            if tool_call["name"] == "write_email":
                # Don't execute the tool, and tell the agent how to proceed
                result.append({"role": "tool", "content": "User ignored this email draft. Ignore this email and end the workflow.", "tool_call_id": tool_call["id"]})
                # Go to END
                goto = END
            elif tool_call["name"] == "schedule_meeting":
                # Don't execute the tool, and tell the agent how to proceed
                result.append({"role": "tool", "content": "User ignored this calendar meeting draft. Ignore this email and end the workflow.", "tool_call_id": tool_call["id"]})
                # Go to END
                goto = END
            elif tool_call["name"] == "Question":
                # Don't execute the tool, and tell the agent how to proceed
                result.append({"role": "tool", "content": "User ignored this question. Ignore this email and end the workflow.", "tool_call_id": tool_call["id"]})
                # Go to END
                goto = END
            else:
                raise ValueError(f"Invalid tool call: {tool_call['name']}")

        elif response["type"] == "response":
            # User provided feedback
            user_feedback = response["args"]
            if tool_call["name"] == "write_email":
                # Don't execute the tool, and add a message with the user feedback to incorporate into the email
                result.append({"role": "tool", "content": f"User gave feedback, which can we incorporate into the email. Feedback: {user_feedback}", "tool_call_id": tool_call["id"]})
            elif tool_call["name"] == "schedule_meeting":
                # Don't execute the tool, and add a message with the user feedback to incorporate into the email
                result.append({"role": "tool", "content": f"User gave feedback, which can we incorporate into the meeting request. Feedback: {user_feedback}", "tool_call_id": tool_call["id"]})
            elif tool_call["name"] == "Question":
                # Don't execute the tool, and add a message with the user feedback to incorporate into the email
                result.append({"role": "tool", "content": f"User answered the question, which can we can use for any follow up actions. Feedback: {user_feedback}", "tool_call_id": tool_call["id"]})
            else:
                raise ValueError(f"Invalid tool call: {tool_call['name']}")

        # Catch all other responses
        else:
            raise ValueError(f"Invalid response: {response}")

    # Update the state
    update = {
        "messages": result,
    }

    return Command(goto=goto, update=update)


def should_continue(state: State) -> Literal["response_interrupt_handler", "__end__"]:
    """
    Determine if the conversation should continue based on the last message.

    Args:
        state (State): The current state of the conversation.
    """

    # Get the last message
    messages = state["messages"]
    last_message = messages[-1]

    # Check if it's a Done tool call
    if last_message.tool_calls:
        for tool_call in last_message.tool_calls:
            if tool_call["name"] == "Done":
                return END
            else:
                return "response_interrupt_handler"

    return END

# Build the graph
agent_builder = StateGraph(State)

# Add nodes
agent_builder.add_node("llm_call", llm_call)
agent_builder.add_node("response_interrupt_handler", response_interrupt_handler)

# Add edges
agent_builder.add_edge(START, "llm_call")
agent_builder.add_conditional_edges(
    "llm_call",
    should_continue,
     {
        "response_interrupt_handler": "response_interrupt_handler",
        END: END
    }
)

# Compile the graph
response_agent = agent_builder.compile()

# View the graph structure
# print(response_agent.get_graph().draw_ascii())

############################################################################
# Build the triage router and overall workflow graph
############################################################################
def triage_router(state: State) -> Command[Literal["triage_interrupt_handler", "response_agent", "__end__"]]:
    """Analyze email content to decide if we should respond, notify, or ignore."""

    author, to, subject, email_thread = parse_email(state["email_input"])
    system_prompt = triage_system_prompt.format(
        background=default_background,
        triage_instructions=default_triage_instructions
    )
    user_prompt = triage_user_prompt.format(
        author=author, to=to, subject=subject, email_thread=email_thread
    )

    # Create email markdown for Agent Inbox in case of notification
    email_markdown = format_email_markdown(subject, author, to, email_thread)

    result = llm_router.invoke(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
    )

    classification = result.classification

    if classification == "respond":
        print(f"📧 Classification: RESPOND - Reasoning: {result.reasoning}")
        goto = "response_agent"
        update = {
            "messages": [
                {
                    "role": "user",
                    "content": f"Respond to the email: \n\n{email_markdown}",
                }
            ],
            "classification_decision": classification,
        }

    elif classification == "ignore":
        print("🚫 Classification: IGNORE - This email can be safely ignored")
        goto = END
        update =  {
            "classification_decision": classification,
        }

    elif classification == "notify":
        print("🔔 Classification: NOTIFY - This email contains important information")
        goto = "triage_interrupt_handler"
        update = {
            "classification_decision": classification,
        }

    else:
        raise ValueError(f"Invalid classification: {classification}")

    return Command(goto=goto, update=update)

def triage_interrupt_handler(state: State) -> Command[Literal["response_agent", "__end__"]]:
    """Handles interrupts from the triage step."""

    # Parse the email input
    author, to, subject, email_thread = parse_email(state["email_input"])

    # Create email markdown for Agent Inbox in case of notification
    email_markdown = format_email_markdown(subject, author, to, email_thread)

    # Create messages
    messages = [{"role": "user", "content": f"Notify about the email: \n\n{email_markdown}"}]

    # Create interrupt that is shown to the user
    request = {
        "action_request": {
            "action": f"Email Assistant: {state['classification_decision'].upper()}",
            "args": {}
        },
        "config": {
            "allow_ignore": True,
            "allow_response": True,
            "allow_edit": False,
            "allow_accept": False,
        },
        "description": email_markdown
    }

    # Agent Inbox responds with a list of dicts with a single key `type` that can be `accept`, `edit`, `ignore`, or `response`.
    response = interrupt([request])[0]

    # If user provides feedback, go to response agent and use feedback to respond to email
    if response["type"] == "response":
        # Add feedback to messages
        user_input = response["args"]
        # Used by the response agent
        messages.append({"role": "user",
                        "content": f"User wants to reply to the email. Use this feedback to respond: {user_input}"
                        })
        # Go to response agent
        goto = "response_agent"

    # If user ignores email, go to END
    elif response["type"] == "ignore":
        goto = END

    # Catch all other responses
    else:
        raise ValueError(f"Invalid response: {response}")

    # Update the state
    update = {
        "messages": messages,
    }

    return Command(goto=goto, update=update)

overall_workflow = (
    StateGraph(State)
    .add_node(triage_router)
    .add_node(triage_interrupt_handler)
    .add_node("response_agent", response_agent)
    .add_edge(START, "triage_router")
)

email_assistant = overall_workflow.compile()