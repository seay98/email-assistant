# Email Assistant

这是一个基于Langchain Academy教学项目，用于学习 LangGraph Agent 开发的邮件助手原型项目。项目目标不是构建完整的生产级邮件系统，而是通过一个小型但完整的例子，练习如何用 LangGraph 组织 Agent 工作流、状态传递、工具调用和结构化输出。

当前项目实现了一个“邮件分流 + 自动回复”的基础流程：

1. 接收一封邮件输入。
2. 使用 LLM 判断邮件应当被忽略、通知，还是需要回复。
3. 如果需要回复，则进入回复 Agent。
4. 回复 Agent 通过工具调用模拟写信和发送邮件。

## 核心功能

### 邮件分流

`email_assistant` 会先分析邮件内容，并将邮件分类为三种结果之一：

- `ignore`：不需要处理的邮件，例如营销邮件、垃圾邮件、无关 FYI。
- `notify`：重要但不需要直接回复的邮件，例如状态更新、提醒、通知类消息。
- `respond`：需要直接回复的邮件，例如会议请求、技术问题、管理层请求、客户询问等。

分类逻辑由 `triage_router` 节点完成，使用结构化输出模型返回 `reasoning` 和 `classification`。

### 回复 Agent

当邮件被分类为 `respond` 时，工作流会进入 `response_agent`。

`response_agent` 会根据系统提示词、用户背景和回复偏好来处理邮件，并通过工具完成动作。当前可用工具包括：

- `write_email(to, subject, content)`：模拟写邮件并发送。
- `triage_email(category)`：记录邮件分类结果。
- `Done`：标记邮件已处理完成。
- `Question`：表示需要向用户追问信息。

注意：当前的 `write_email` 只是占位实现，并不会真正调用邮箱 API 发送邮件。

## 工作流说明

项目在 `langgraph.json` 中暴露了两个 graph：

- `email_assistant`：完整邮件助手工作流，包含邮件分流和按需回复。
- `response_agent`：只负责回复生成和工具调用的子 Agent。

完整流程如下：

```text
START
  |
  v
triage_router
  |
  |-- ignore --> END
  |
  |-- notify --> END
  |
  |-- respond --> response_agent
                    |
                    v
                  END
```

其中 `response_agent` 内部是一个循环：

```text
llm_call -> tool_handler -> llm_call -> ... -> Done
```

模型每轮必须调用一个工具，直到调用 `Done` 表示任务完成。

## 项目结构

```text
.
├── langgraph.json
├── main.py
├── pyproject.toml
├── README.md
└── src/
    └── email_assistant/
        ├── assistant.py
        ├── prompts.py
        ├── schemas.py
        ├── utils.py
        └── tools/
            └── default/
                ├── email_tools.py
                └── prompt_tools.py
```

关键文件说明：

- `src/email_assistant/assistant.py`：项目核心文件，定义 LLM、tools、`response_agent` 和 `email_assistant` 两个 LangGraph 工作流。
- `src/email_assistant/prompts.py`：保存系统提示词、邮件分类规则、用户背景和默认回复偏好。
- `src/email_assistant/schemas.py`：定义 graph state 和邮件分类的结构化输出 schema。
- `src/email_assistant/utils.py`：提供邮件输入解析和 Markdown 格式化工具函数。
- `src/email_assistant/tools/default/email_tools.py`：定义邮件相关工具，包括模拟发送邮件、分类、完成标记和提问工具。
- `src/email_assistant/tools/default/prompt_tools.py`：定义工具说明 prompt。
- `langgraph.json`：LangGraph CLI 配置文件，声明可运行的 graph 和环境变量文件。

## 环境配置

项目使用 Python 3.13，并依赖 LangGraph、LangChain 和 OpenAI 兼容接口。

安装依赖：

```bash
uv sync
```

创建 `.env` 文件，并配置模型服务所需的 API Key：

```env
ARK_API_KEY=your_api_key_here
```

当前代码通过 OpenAI 兼容接口调用火山方舟服务：

- `glm-4-7-251222`：用于回复 Agent。
- `doubao-seed-1-8-251228`：用于邮件分类的结构化输出。

## 运行方式

可以通过 LangGraph CLI 启动本地开发服务，并使用LangSmith进行调用和调试：

```bash
uv run langgraph dev
```

启动后可以在 LangGraph Studio（需要对LangSmith进行相应设置） 或 API 中调用 `email_assistant` graph

示例输入结构：

```json
{
  "email_input": {
    "author": "Alice <alice@example.com>",
    "to": "Seay <seay@example.com>",
    "subject": "Meeting request",
    "email_thread": "Hi Seay, can we schedule a 30-minute meeting next week to discuss the project?"
  }
}
```

如果邮件被判断为需要回复，graph 会进入 `response_agent` 并生成一封模拟发送的回复邮件。

## 当前限制

这个项目仍在开发中，目前有一些明确的限制：

- `write_email` 只是 placeholder，不会真正发送邮件。
- `notify` 分类目前只结束流程，还没有实际通知机制。
- prompt 中提到了 `check_calendar_availability`，但代码中尚未实现日历工具。
- 用户背景和回复偏好目前写死在 `prompts.py` 中，尚不能动态配置。
- 还没有接入真实邮箱 API。
- 还没有测试用例。
- `main.py` 只是默认示例入口，不是项目的实际运行入口。

## 后续计划

后续可以围绕下面几个方向继续完善：

- 接入 Gmail、Outlook 或其他邮箱 API，实现真实读取和发送邮件。
- 为 `notify` 分类增加通知机制，例如桌面通知、消息队列或待办事项。
- 实现日历工具，用于检查会议可用时间。
- 将用户背景、回复风格和 triage 规则改成可配置项。
- 增加测试用例，覆盖邮件解析、分类路由和工具调用。
- 增加更完整的运行示例和调试说明。

## 学习重点

这个项目适合用来练习以下 LangGraph / Agent 开发概念：

- 使用 `StateGraph` 构建工作流。
- 使用 `Command` 控制节点跳转和 state 更新。
- 使用 structured output 做稳定的路由决策。
- 使用 tools 扩展 Agent 能力。
- 将一个子 graph 作为节点接入更大的 workflow。
- 用 prompt 管理 Agent 的角色、行为约束和回复偏好。
