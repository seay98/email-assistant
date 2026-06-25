# Outlook 工具说明

`src/email_assistant/tools/outlook` 用于把 Outlook / Hotmail 邮箱中的邮件读取出来，并送入本项目的 LangGraph 邮件助手工作流。当前实现覆盖了 Microsoft Graph 设备码认证、邮件抓取、邮件字段规范化、LangGraph run 创建，以及几类手动测试脚本。

## 功能概览

### Microsoft Graph 认证

`setup_outlook.py` 使用 Microsoft OAuth device code flow 完成登录授权。这个流程适合 WSL、远程终端和无浏览器回调地址的开发环境。

认证成功后，脚本会把 token 保存到：

```text
src/email_assistant/tools/outlook/.secrets/token.json
```

后续抓取邮件时会优先读取环境变量 `OUTLOOK_TOKEN`，如果没有设置，则读取上面的 `token.json`。当 token 即将过期且包含 `refresh_token` 时，代码会自动刷新并写回本地 token 文件。

### Outlook 邮件抓取

`outlook_tools.py` 通过 Microsoft Graph `me/messages` API 拉取邮件，并做下面几件事：

- 使用 `$select` 只读取邮件助手需要的字段。
- 默认按 `receivedDateTime desc` 排序。
- 默认只抓取最近 `--hours-since` 小时内的未读邮件。
- 可选使用 `--email` 做客户端过滤，保留发件人或收件人匹配该地址的邮件。
- 将 Graph message 规范化成 LangGraph ingestion 使用的字段。

规范化后的字段包括：

```text
from_email
to_email
subject
page_content
id
thread_id
send_time
```

### 写入 LangGraph

`run_ingest.py` 会先从 Outlook 抓取邮件，然后把每封邮件送入 LangGraph。

处理逻辑如下：

1. 使用 Outlook `conversationId` 生成稳定的 LangGraph `thread_id`。
2. 如果 thread 已存在，并且 metadata 中的 `email_id` 与当前邮件相同，则默认跳过，避免重复处理。
3. 如果使用 `--rerun`，则即使邮件已处理过也会重新创建 run。
4. 如果 thread 已存在，会删除之前的 runs，再创建新的 run。
5. 将邮件内容写入 graph input 的 `email_input` 字段。

发送给 graph 的输入结构如下：

```json
{
  "email_input": {
    "author": "Alice <alice@example.com>",
    "to": "Seay <seay@example.com>",
    "subject": "邮件主题",
    "email_thread": "邮件正文",
    "id": "outlook-message-id"
  }
}
```

## 文件说明

- `setup_outlook.py`：完成 Outlook / Hotmail 的 Microsoft Graph 授权，并保存 token。
- `outlook_tools.py`：加载和刷新 token、调用 Microsoft Graph、过滤和规范化邮件。
- `run_ingest.py`：抓取真实 Outlook 邮件，并创建 LangGraph run。
- `test_fetch.py`：测试 Outlook 抓取链路，可运行 mock、本地 filter 测试或真实 Graph 抓取。
- `test_fetch_commands.sh`：常用 `test_fetch.py` 命令封装。
- `test_ingest.py`：使用合成邮件测试 LangGraph ingestion，不需要 Microsoft Graph 凭据。
- `.secrets/`：本地密钥和 token 目录，不应提交到 git。

## 前置条件

安装项目依赖：

```bash
uv sync
```

如果要抓取真实 Outlook / Hotmail 邮件，需要一个 Microsoft Entra 应用注册，并允许个人 Microsoft 账号登录。默认 scopes 是：

```text
Mail.Read
User.Read
offline_access
```

### Microsoft 账号和 API 权限设置

`setup_outlook.py` 只能在 Microsoft 账号和应用注册都配置正确后获得 token。运行脚本前，需要先在 Microsoft Entra 管理中心为当前邮箱账号准备一个应用，并开通 Microsoft Graph 的委托权限。

基本设置步骤：

1. 进入 Microsoft Entra 管理中心，创建 App registration。
2. 在 Supported account types 中选择允许你的邮箱账号登录的类型：
   - 如果使用 `@outlook.com`、`@hotmail.com` 等个人 Microsoft 账号，选择支持 personal Microsoft accounts 的选项。
   - 如果使用公司或学校账号，选择对应组织账号类型，并确认租户允许该应用登录。
3. 在 Authentication 中启用 public client / mobile and desktop client flow。当前脚本使用 device code flow，不需要 client secret。
4. 在 API permissions 中添加 Microsoft Graph 的 Delegated permissions：
   - `Mail.Read`：读取邮箱邮件。
   - `User.Read`：读取当前登录用户基础信息。
   - `offline_access`：获取 refresh token，用于后续自动刷新 access token。
5. 如果使用公司或学校账号，可能还需要管理员同意这些权限，或管理员允许用户自行 consent。否则登录时可能会被租户策略拦截。
6. 复制应用的 Application (client) ID，作为下面的 `client_id` 使用。

可以通过两种方式配置 `client_id`。

方式一：创建本地 secrets 文件：

```json
{
  "client_id": "your_microsoft_graph_client_id",
  "tenant": "consumers",
  "scopes": ["Mail.Read", "User.Read", "offline_access"]
}
```

保存到：

```text
src/email_assistant/tools/outlook/.secrets/secrets.json
```

方式二：在项目 `.env` 中设置：

```env
HOTMAIL_GRAPH_CLIENT_ID=your_microsoft_graph_client_id
```

## 首次授权

运行：

```bash
uv run python src/email_assistant/tools/outlook/setup_outlook.py
```

脚本会输出 Microsoft 登录地址和一次性 user code。按提示在浏览器中登录并授权后，token 会保存到 `.secrets/token.json`。

也可以通过测试命令脚本运行：

```bash
bash src/email_assistant/tools/outlook/test_fetch_commands.sh setup
```

## 抓取邮件测试

### 本地 mock 测试

不需要 Microsoft token，也不需要网络：

```bash
uv run python src/email_assistant/tools/outlook/test_fetch.py --mock
```

这个命令只验证 Graph message 到内部 email data 的字段转换。

### 查看 OData filter

不调用 Microsoft Graph，只打印即将使用的服务端过滤条件：

```bash
uv run python src/email_assistant/tools/outlook/test_fetch.py \
  --hours-since 24 \
  --print-filter
```

如果想验证跳过过滤：

```bash
uv run python src/email_assistant/tools/outlook/test_fetch.py \
  --skip-filters \
  --print-filter
```

### 真实抓取邮件

需要先完成 `setup_outlook.py` 授权：

```bash
uv run python src/email_assistant/tools/outlook/test_fetch.py \
  --hours-since 24 \
  --include-read \
  --limit 5
```

如果要查找更早的已读邮件，`--include-read` 需要配合更大的时间范围，或直接关闭时间过滤：

```bash
uv run python src/email_assistant/tools/outlook/test_fetch.py \
  --include-read \
  --hours-since 0 \
  --limit 10
```

显示正文预览：

```bash
uv run python src/email_assistant/tools/outlook/test_fetch.py \
  --hours-since 24 \
  --include-read \
  --limit 5 \
  --show-body
```

也可以使用封装脚本：

```bash
bash src/email_assistant/tools/outlook/test_fetch_commands.sh local
bash src/email_assistant/tools/outlook/test_fetch_commands.sh fetch
bash src/email_assistant/tools/outlook/test_fetch_commands.sh fetch-body
```

`test_fetch_commands.sh` 默认不传 `--email`，只使用时间范围和输出数量配置。需要收窄到某个地址时，可以临时设置 `EMAIL`：

```bash
EMAIL=other@example.com HOURS_SINCE=48 LIMIT=10 \
  bash src/email_assistant/tools/outlook/test_fetch_commands.sh fetch
```

## 写入 LangGraph

先启动 LangGraph 本地服务：

```bash
uv run langgraph dev
```

默认服务地址是：

```text
http://127.0.0.1:2024
```

然后运行真实 Outlook ingestion：

```bash
uv run python src/email_assistant/tools/outlook/run_ingest.py \
  --hours-since 24 \
  --graph-name email_assistant \
  --url http://127.0.0.1:2024
```

常用参数：

- `--email`：可选。用于客户端侧匹配发件人或收件人；不传时返回当前 token mailbox 中满足其他条件的邮件。
- `--hours-since`：只读取最近多少小时的邮件，默认 `2`；设为 `0` 可关闭时间过滤。
- `--no-time-filter`：只关闭时间过滤，保留已读状态和邮箱匹配过滤。
- `--graph-name`：LangGraph graph 名称，默认 `email_assistant`。
- `--url`：LangGraph 服务地址，默认 `http://127.0.0.1:2024`。
- `--early`：只处理第一封匹配邮件，适合调试。
- `--include-read`：包含已读邮件。默认只抓未读邮件；查历史已读邮件时还要增大 `--hours-since` 或关闭时间过滤。
- `--rerun`：同一封邮件即使已经处理过，也重新创建 run。
- `--wait`：等待每个 LangGraph run 完成，并打印最终 state 摘要。
- `--skip-email-filter`：跳过发件人/收件人邮箱匹配，保留服务端时间和已读状态过滤。
- `--skip-filters`：兼容旧参数，跳过时间、未读和邮箱匹配过滤。
- `--fetch-limit`：Microsoft Graph 每页抓取数量，默认 `25`；`test_fetch.py` 的 `--limit` 只控制打印数量。

调试时推荐先只处理一封，并等待结果：

```bash
uv run python src/email_assistant/tools/outlook/run_ingest.py \
  --hours-since 24 \
  --include-read \
  --early \
  --wait \
  --rerun
```

## LangGraph ingestion 测试

`test_ingest.py` 使用一封合成邮件测试写入 LangGraph 的路径。它不需要 Microsoft Graph token，但需要本地 LangGraph 服务正在运行。

```bash
uv run langgraph dev
```

另一个终端运行：

```bash
uv run python src/email_assistant/tools/outlook/test_ingest.py
```

测试会检查：

- 是否成功创建 LangGraph thread 和 run。
- thread metadata 中是否写入 `email_id`。
- state 中是否存在 `email_input`。
- graph 是否产出 `classification_decision`。

可以指定服务地址、graph 名称、合成 conversation id 和 email id：

```bash
uv run python src/email_assistant/tools/outlook/test_ingest.py \
  --url http://127.0.0.1:2024 \
  --graph-name email_assistant \
  --conversation-id synthetic-outlook-conversation-001 \
  --email-id synthetic-outlook-email-001
```

默认会 `--rerun`，因此重复运行测试也会重新处理同一封合成邮件。若要验证跳过重复处理，可以使用：

```bash
uv run python src/email_assistant/tools/outlook/test_ingest.py --no-rerun
```

## 凭据和安全

`.secrets/token.json` 里包含 access token 和 refresh token，应只保存在本地开发环境。不要把 `.secrets/`、`token.json` 或真实 token 内容提交到 git。

如果不想落盘 token，可以设置 `OUTLOOK_TOKEN` 环境变量，内容是完整 token JSON 字符串：

```bash
export OUTLOOK_TOKEN='{"access_token":"...","refresh_token":"...","client_id":"..."}'
```

## 常见问题

### 找不到 token

先运行：

```bash
uv run python src/email_assistant/tools/outlook/setup_outlook.py
```

确认生成了：

```text
src/email_assistant/tools/outlook/.secrets/token.json
```

### token 过期或刷新失败

如果 token 缺少 `refresh_token`、`client_id`，或 Microsoft 返回刷新错误，重新运行 `setup_outlook.py` 完成授权。

### 没有抓到邮件

默认只抓最近 2 小时内的未读邮件。邮件是通过当前 token 调用 `/me/messages` 获取的，所以不传 `--email` 时就是当前 mailbox 中满足时间和已读状态条件的邮件。`--include-read` 只表示包含已读邮件，不会自动取消时间范围。可以尝试：

```bash
uv run python src/email_assistant/tools/outlook/test_fetch.py \
  --hours-since 72 \
  --include-read
```

如果要确认历史已读邮件是否能返回，用：

```bash
uv run python src/email_assistant/tools/outlook/test_fetch.py \
  --include-read \
  --hours-since 0 \
  --limit 10 \
  --show-body
```

如果只是想确认 Graph API 能返回邮件，可以临时加 `--skip-filters`。

### ingestion 连接失败

确认 LangGraph 服务已经启动，并且 `--url` 指向正确地址：

```bash
uv run langgraph dev
```

默认本地地址是 `http://127.0.0.1:2024`。

### 重复邮件被跳过

`run_ingest.py` 会把 Outlook message id 写入 thread metadata 的 `email_id`。如果同一个 conversation thread 已经处理过同一封邮件，默认会跳过。调试时可以加：

```bash
--rerun
```
