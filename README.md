# Email Assistant

一个用于学习 LangGraph Agent 开发的邮件助手原型项目，来源于 LangChain Academy 教学项目。项目核心流程是“邮件分流 + 按需回复”：收到邮件后，模型先判断是否需要处理；只有需要回复的邮件才会进入回复 Agent。

这个项目适合练习 LangGraph 工作流编排、structured output 路由、状态传递、工具调用，以及把真实邮箱数据接入本地 LangGraph 服务。

## 功能概览

- 邮件分流：`email_assistant` graph 会将邮件分类为 `ignore`、`notify` 或 `respond`。
- 回复 Agent：当分类为 `respond` 时，`response_agent` 会调用默认工具生成一封模拟回复。
- Outlook / Hotmail 接入：`src/email_assistant/tools/outlook` 可以通过 Microsoft Graph 抓取邮件并写入 LangGraph；详细配置和使用方式见 [Outlook 工具说明](src/email_assistant/tools/outlook/README.md)。

注意：默认发信工具是 placeholder，只返回模拟发送结果，不会真正调用邮箱 API 发信。

## 工作流

`langgraph.json` 暴露两个 graph：

- `email_assistant`：完整邮件助手工作流。
- `response_agent`：只负责回复生成和工具调用的子 Agent。

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
  |-- respond --> response_agent --> END
```

## 项目结构

```text
.
├── langgraph.json
├── pyproject.toml
├── README.md
└── src/
    └── email_assistant/
        ├── assistant.py
        ├── prompts.py
        ├── schemas.py
        ├── utils.py
        └── tools/
            ├── default/
            └── outlook/
```

关键文件：

- `src/email_assistant/assistant.py`：定义 LLM、tools、`response_agent` 和 `email_assistant` 工作流。
- `src/email_assistant/prompts.py`：保存系统提示词、分类规则、用户背景和回复偏好。
- `src/email_assistant/schemas.py`：定义 graph state 和邮件分类 structured output schema。
- `src/email_assistant/tools/default/`：默认邮件工具，目前为模拟实现。
- `src/email_assistant/tools/outlook/`：Outlook / Hotmail 邮件抓取和 ingestion 工具。

## 环境配置

项目使用 Python 3.13，并通过 `uv` 管理依赖。

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
- `doubao-seed-1-8-251228`：用于邮件分类 structured output。

## 本地运行

启动 LangGraph 本地开发服务：

```bash
uv run langgraph dev
```

默认服务地址是 `http://127.0.0.1:2024`。可以在 LangGraph Studio 或 API 中调用 `email_assistant` graph。

示例输入：

```json
{
  "email_input": {
    "author": "Alice <alice@example.com>",
    "to": "Seay <seay@example.com>",
    "subject": "Meeting request",
    "email_thread": "Hi Seay, can we schedule a 30-minute meeting next week?"
  }
}
```

如果要接入 Outlook / Hotmail 邮箱，请查看 [Outlook 工具说明](src/email_assistant/tools/outlook/README.md)。

## 当前限制与后续计划

- 默认 `write_email` 不会真正发送邮件，后续可替换为真实发信工具。
- `notify` 分类目前只结束流程，后续可接入通知、待办或消息队列。
- prompt 中提到了日历能力，但项目尚未实现日历工具。
- 实现human-in-the-loop。
- 增加memory。
