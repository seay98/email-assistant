import os
from typing import Literal

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from pydantic import SecretStr

from email_assistant.schemas import RouterSchema, State
from email_assistant.tools.default.email_tools import Done, Question, triage_email, write_email
from email_assistant.tools.default.prompt_tools import AGENT_TOOLS_PROMPT
from email_assistant.prompts import triage_user_prompt, triage_system_prompt, default_triage_instructions, assistant_system_prompt, default_background, default_response_preferences
from email_assistant.utils import format_email_markdown, parse_email

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
                     "content": assistant_system_prompt.format(
                         tools_prompt=AGENT_TOOLS_PROMPT,
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

def should_continue(state: State) -> Literal["tool_handler", "__end__"]:
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
                return "tool_handler"
    
    return END
            
# Build the graph
agent_builder = StateGraph(State)

# Add nodes
agent_builder.add_node("llm_call", llm_call)
agent_builder.add_node("tool_handler", tool_handler)

# Add edges
agent_builder.add_edge(START, "llm_call")
agent_builder.add_conditional_edges(
    "llm_call",
    should_continue,
     {
        "tool_handler": "tool_handler",
        END: END
    }
)
agent_builder.add_edge("tool_handler", "llm_call")

# Compile the graph
response_agent = agent_builder.compile()

# View the graph structure
# print(response_agent.get_graph().draw_ascii())

############################################################################
# Build the triage router and overall workflow graph
############################################################################
def triage_router(state: State) -> Command[Literal["response_agent", "__end__"]]:
    """Analyze email content to decide if we should respond, notify, or ignore."""

    author, to, subject, email_thread = parse_email(state["email_input"])
    system_prompt = triage_system_prompt.format(
        background=default_background,
        triage_instructions=default_triage_instructions
    )
    user_prompt = triage_user_prompt.format(
        author=author, to=to, subject=subject, email_thread=email_thread
    )

    result = llm_router.invoke(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
    )

    if result.classification == "respond":
        print(f"📧 Classification: RESPOND - Reasoning: {result.reasoning}")
        goto = "response_agent"
        update = {
            "messages": [
                {
                    "role": "user",
                    "content": f"Respond to the email: \n\n{format_email_markdown(subject, author, to, email_thread)}",
                }
            ],
            "classification_decision": result.classification,
        }

    elif result.classification == "ignore":
        print("🚫 Classification: IGNORE - This email can be safely ignored")
        goto = END
        update =  {
            "classification_decision": result.classification,
        }
        
    elif result.classification == "notify":
        print("🔔 Classification: NOTIFY - This email contains important information")
        # For now, we go to END. But we will add to this later!
        goto = END
        update = {
            "classification_decision": result.classification,
        }
    
    else:
        raise ValueError(f"Invalid classification: {result.classification}")
    
    return Command(goto=goto, update=update)


overall_workflow = (
    StateGraph(State)
    .add_node(triage_router)
    .add_node("response_agent", response_agent)
    .add_edge(START, "triage_router")
)

email_assistant = overall_workflow.compile()