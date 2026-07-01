# Email Assistant

一个用于学习 LangGraph Agent 开发的邮件助手原型项目，来源于 LangChain Academy 教学项目。项目核心流程是“邮件分流 + 按需回复 + 偏好记忆”：收到邮件后，模型先判断是否需要处理；只有需要回复的邮件才会进入回复 Agent；用户在 Agent Inbox 中的反馈会被写入 LangGraph store，用于后续分流和回复偏好的调整。

这个项目适合练习 LangGraph 工作流编排、structured output 路由、状态传递、工具调用，以及把真实邮箱数据接入本地 LangGraph 服务。

## 功能概览

- 邮件分流：`email_assistant` graph 会将邮件分类为 `ignore`、`notify` 或 `respond`，并优先使用 store 中的 `triage_preferences` 记忆；首次运行时会用默认分流规则初始化。
- 回复 Agent：当分类为 `respond` 时，`response_agent` 会调用默认工具生成一封模拟回复，并使用 store 中的 `response_preferences` 记忆控制回复风格。
- 人工确认：当分类为 `notify` 时，流程会进入 Agent Inbox，用户可以忽略邮件，也可以补充反馈并转入回复 Agent。
- HITL 审核：回复草稿和问题类工具调用会先进入人工审核，再决定接受、编辑、补充反馈或忽略；编辑、反馈和忽略动作会用于更新相关偏好记忆。
- 偏好记忆：工作流会通过 LangGraph store 读取和更新用户偏好，让后续邮件分流和回复草稿参考历史反馈。
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
  |-- notify --> triage_interrupt_handler
  |                 |
  |                 |-- ignore --> END
  |                 |
  |                 |-- respond --> response_agent --> END
  |
  |-- respond --> response_agent --> END
```

## 偏好记忆

项目现在会把用户在 Agent Inbox 中的反馈沉淀为可复用的偏好资料。记忆保存在 LangGraph store 中，默认 key 为 `user_preferences`，并按 namespace 区分用途：

- `("email_assistant", "triage_preferences")`：邮件分流偏好，用来影响后续 `ignore`、`notify`、`respond` 分类。
- `("email_assistant", "response_preferences")`：回复偏好，用来影响后续邮件草稿的语气、结构和内容取舍。
- `("email_assistant", "cal_preferences")`：日历偏好，预留给会议邀请编辑和日历相关反馈。

首次读取时，如果 store 中没有对应记忆，会使用 `prompts.py` 中的默认偏好初始化。之后以下操作会触发偏好更新：

- 用户在 `notify` 审核中选择回复或忽略。
- 用户忽略回复草稿、问题或会议草稿。
- 用户编辑回复草稿或会议邀请。
- 用户对回复草稿或会议邀请补充反馈。

记忆更新由 `MEMORY_UPDATE_INSTRUCTIONS` 约束：只做有针对性的增量更新，保留未被反馈直接推翻的原有偏好。

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

- `src/email_assistant/assistant.py`：定义 LLM、tools、偏好记忆读写函数、`response_agent` 和 `email_assistant` 工作流。
- `src/email_assistant/prompts.py`：保存系统提示词、分类规则、用户背景、默认回复偏好和记忆更新提示词。
- `src/email_assistant/schemas.py`：定义 graph state、邮件分类 structured output schema，以及记忆更新的 `UserPreferences` 输出 schema。
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
- `doubao-seed-1-8-251228`：用于邮件分类 structured output 和偏好记忆更新。

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
- prompt 和偏好记忆逻辑中提到了日历能力与 `cal_preferences`，但项目尚未实现真实日历工具。
- 目前偏好记忆依赖 LangGraph store；如果使用临时内存 store，本地服务重启后偏好可能不会保留。
- 记忆更新由模型根据人工反馈增量合并，适合原型验证；生产环境应增加可观测性、回滚和人工校验。
