# lingguang-mcp

灵光 AI 的 MCP 与 CLI 工具。替 Agent 向灵光提问、取回结论、记录执行轨迹。

## 这个工具解决什么问题

支付宝账单、钉钉消息这两件事，对个人没有独立的开放接口：

- 支付宝不向个人开放账单 API
- 钉钉需要企业管理员开启数据访问权限

灵光是唯一入口。它已经拿到支付宝授权、已经连上钉钉，
并且能通过 Agent 真实查询账单（返回每笔交易的商户、金额、时间）。

所以这个工具本质上是一个**遥控器加录音机**：
替用户向灵光提问、取回结论、记录 Agent 的执行轨迹。
它无法绕过灵光自己去拿数据。

## 核心能力

- 提问并取回结论（20 到 30 秒的长任务，异步两段式）
- 读取历史会话的正文
- 读取 Agent 的工具执行轨迹（这是别的方案给不了的）
- 导出归档

## 安装

```bash
uv sync
```

## 获取 cookie

1. 浏览器登录 https://www.lingguang.com
2. 打开开发者工具，进入 Application 或 Storage 中的 Cookie
3. 找到 `ctoken`、`prod_LINGGUANGJSESSIONID`、`spanner` 三个值
4. 拼成 `name=value; name=value` 格式，写入文件

```bash
lingguang auth import cookie.txt
lingguang auth status
```

## CLI

```bash
lingguang sessions list
lingguang sessions show <session-id>
lingguang ask "这个月吃饭花了多少" --wait
lingguang export <session-id> --format md -o out.md
lingguang doctor
```

## MCP

```bash
lingguang serve
```

在 opencode 配置里挂载：

```json
{
  "mcp": {
    "lingguang": {
      "type": "local",
      "command": ["lingguang", "serve"]
    }
  }
}
```

## 可用工具

| 工具 | 用途 |
|---|---|
| `list_sessions` | 列出会话 |
| `get_transcript` | 读取会话正文与工具轨迹 |
| `ask` | 提交提问，立即返回 |
| `get_answer` | 取回提问结果 |
| `auth_status` | 检查登录态 |
| `delete_session` | 删除会话，需显式确认 |

## 设计文档

完整工程方案见 [ENGINEERING-PLAN.md](ENGINEERING-PLAN.md)，
接口逆向记录见 [docs/reverse-notes.md](docs/reverse-notes.md)。

两条重要约束：

- **本工具设计为低频人级调用。** 蚂蚁侧有风控，高频轮询会让账号被标记，
  那会连带影响你在灵光 App 里的正常使用。不要拿它做爬虫。
- **解析器失败时用 `export --format raw` 兜底。** 原始 JSON 仍有归档价值。

## 分层约束

`cli/` 和 `mcp/` 只准 import `core` 下的 `service`、`models`、`errors`，
不准直接碰 `client` 和 `parser`。这样维护者能一眼看出哪些是稳定接口。
