# 灵光 MCP / CLI 工具工程方案

基于 2026-10-28 全部实测数据。所有设计决策都标注了对应的实测依据。

---

## 零、使用场景（这是所有设计的出发点）

**核心前提：支付宝账单、钉钉这两件事，没有独立的开放接口可以用。**

支付宝不给个人用户开放账单 API，钉钉这边也需要企业管理员开数据访问权限，
而且灵光连接时已经踩过这个坑（组织未开放 CLI 数据访问）。

所以灵光的价值是**唯一入口**：它已经拿到了支付宝授权，已经把账单查出来，
已经连上了钉钉。这些能力只能通过灵光这个 Agent 间接使用。

**由此推出的三条铁律：**

1. 工具的价值在"拿到灵光算好的结论"，不在"自己算"。
   自己算没有数据源，这是死路。
2. 工具必须是 Agent 的**遥控器和录音机**，不是替代品。
   它能做的只是：替我发问、替我取结果、替我把轨迹记下来。
3. 稳定性优先级最高。这是唯一入口，它挂了就没有替代方案。
   所以解析器要有契约测试，错误要分类清楚。

**典型使用场景：**

- "这个月吃饭花了多少" -> 发给灵光 -> 取回结论
- "9 月账单里有哪些大额支出" -> 发问 -> 拿结论和工具轨迹
- 把历史问答导出存档，防止 App 侧数据丢失
- 批量问一系列问题，把结果汇总成表格

---

## 一、这不是单纯的 API 包装

逆向结论表明，灵光本质上是"移动端授权的 Agent 宿主"，网页或 HTTP 只是遥控器。
这套工具的真实价值不在"调用大模型"，而在三件事：

1. **账单/钉钉等工具的真实执行轨迹**。Agent 每一步调了什么子程序，
   标题都写在事件流里，这是其他 LLM 给不了的结构化信息。
2. **拿到结构化后的结论**，不用自己写 SQL 聚合（也没有原始数据可写 SQL）。
3. **持久归档**。会话本来只能在 App 里翻，导出后可以做时序分析。

所以工具定位应该是 **"Agent 执行记录与结论的采集器"**，顺带提供提问能力。
如果定位成"又一个聊天客户端"，投入产出比很低。

---

## 二、实测约束清单（设计必须先满足这些）

| # | 约束 | 实测证据 | 设计影响 |
|---|---|---|---|
| 1 | sceneCode 分两套 | 历史/删除用 `LEOPARD`，提问用 `WEB` | 按接口分派，不统一常量 |
| 2 | **可新建会话** | 客户端生成 UUID 作为 sessionId 即可，服务端直接采用 | `ask` 支持自动建会话 |
| 3 | sessionId 空值不可用 | 空串 / 省略字段均 500 | 只能用合法 UUID |
| 4 | 跨场景数据不隔离 | `sceneCode=WEB` 与 `LEOPARD` 返回同一份完整列表 | 不必分场景拉取再合并 |
| 5 | pageSize 上限 30 | 31 返回 `SYSTEM_ERROR` | 必须分页 |
| 6 | SSE 不能用 iter_lines | 多字节被截断出现 `\x89` | 按字节切 `\n\n` 分帧 |
| 7 | 正文藏在 artifact | `AgentEventRenderer.render` 事件流 | 需专用解析器 |
| 8 | 提问返回是增量帧 | 正文要回查才齐 | 提交与取结果分离 |
| 9 | **轮次不会被半截查出** | 任务跑完前历史接口查不到该轮；完成后一次性 `status=VALID`，正文完整 | `get_answer` 只需判断"有没有"，无需判断"完不完整" |
| 10 | 删除幂等 | 不存在 id 也返回 SUCCESS | 不用处理 404 |
| 11 | 直连可用 | 310ms，无需代理 | 部署简单 |
| 12 | 分页游标 | `latestTime` + `hasMore` | best-effort，不保证无遗漏 |

### 约束 2 的实测细节（最重要的一条修正）

之前误判为"无法新建会话"，因为传 `null`、空串、省略字段全都 500。
实际网页端的做法是**客户端自己生成 UUID 当 sessionId**：

```
sessionId=""          -> 500
sessionId 省略         -> 500
sessionId=<新UUID>    -> 200，会话真的建出来
```

验证：生成 `93a11295-eff7-4efa-938f-b79cc591c278` 发问，
随后会话列表里出现该 id，标题自动取回复首句"收到"。

**影响**：`ask` 的 `session_id` 参数改为可选，不传就自动建新会话。

### 约束 4 的实测细节

传 `sceneCode=WEB` 和 `sceneCode=LEOPARD` 查询会话列表，
返回的是同一份数据（6 条完全相同）。说明场景字段用于标识来源，
不做数据隔离。所以 `list_sessions` 固定传一个值即可拿到全部。

注意：App 发起的会话 `sceneCode` 是 `LEOPARD`，网页发起的是 `WEB`，
这个字段要原样保留，用于追溯来源。

### 约束 9 的实测细节（决定 get_answer 能否正确收尾）

新建会话 `863db287` 发出"帮我看看这个月吃饭花了多少钱"，然后轮询历史接口：

```
t=3s   查到 0 条（任务进行中，历史接口里没有这一轮）
t=4s   查到 1 条 status=VALID len=22641（已完成，正文完整）
```

结论：**服务端是原子的，任务完成前不写入历史，写入时就是完整状态。**
不存在"正文被截断但 status 为 VALID"的情况。

这大大简化了 `get_answer`：只需判断"这一轮出现了没有"，
不需要猜"内容够不够完整"。出现即可信。

仍保留一层防御：如果查到的 `text` 长度异常短（<50 字符）
且该轮带工具轨迹，标记 `warnings`，交给人判断。

### 约束 12 的实测细节

`latestTime` 是时间戳游标。同一毫秒内创建多个会话可能漏读，
且翻页过程中若有新会话写入，结果会漂移。

所以游标是 **best-effort**。需要严格全量时走 `export` 全量拉取，
或者按 session id 去重，不要依赖游标保证无遗漏。

---

## 三、核心架构决策

### 决策一：MCP 与 CLI 共用同一个 core

不要写两遍。CLI 是 core 的薄壳，MCP 也是 core 的薄壳。

```
lingguang/
  core/
    client.py      # HTTP 传输层
    models.py      # 数据模型
    parser.py      # artifact / cot 双通道解析
    service.py     # 业务编排，MCP 与 CLI 都调它
    errors.py      # 四级异常分类
```

关键点：`service.py` 的每个方法都应能在 CLI 里单独调。
如果某个能力只能在 MCP 里用，说明分层错了。

### 决策二：传输层用 STDIO，不用 HTTP

MCP 规范最新版 **2026-07-28**。Streamable HTTP 在该版本移除了 GET 流端点和
协议级 session，已经是无状态的，但本地场景仍应选 stdio。

依据：
- 规范原文 "Clients SHOULD support stdio whenever possible"
- 单客户端、单机、无远程需求，HTTP 只会增加负担
- Streamable HTTP 强制要求校验 `Origin` 头防 DNS 重绑定、做鉴权、
  本地建议只绑 127.0.0.1，这些都是额外工作

stdio 的唯一约束：**stdout 只能写合法 MCP 消息，所有日志必须走 stderr**。

实现上最省事的做法：在 `mcp/server.py` 启动时立刻把 `sys.stdout`
重定向到 `sys.stderr`，最后再把真正的 stdout 句柄交给 MCP 传输层。
这样任何第三方库顺手 `print` 都不会破坏协议帧。

### 决策三：提问必须异步化

账单分析跑 20 到 30 秒。MCP 工具同步阻塞会撞各种超时，
调用方也没法中途取消。拆成两段：

- `ask` 提交提问，立即返回 `session_id` 和 `query_id`
- `get_answer` 按 `query_id` 查结果，带 `wait_seconds` 做短暂轮询

CLI 侧提供 `--wait` 参数做阻塞封装，内部还是这两段。

**不在服务端起后台线程。** SSE 读完或超时就断开，"异步"由调用方这一侧承担。
MCP server 保持无状态、无线程管理负担。

### 决策三之补：ask 必须可恢复

这是评审指出最痛的问题。`ask` 不重试是对的（会重复下单），
但 SSE 断流时调用方会失去对这次提问的控制。如果不设计恢复路径，
agent 很可能重发一次，导致账单被查询两遍。

已有的天然幂等键：**`session_id` 和 `query_id` 都是我方生成的 UUID**。

设计：

1. `ask` 提交前，把 `(session_id, query_id, query, submitted_at)`
   追加写入一份 pending journal，位置 `~/.cache/lingguang/pending.jsonl`。
   这份文件只记录**尚未确认完成的提问**，不存历史数据，不涉及数据同步问题。
2. SSE 中途断流**不抛 TransportError**。返回
   `{status: "dispatched_unknown", session_id, query_id}`，
   告诉调用方"已发出，结果未知"。
3. `get_answer` 查不到 query_id 时，退化为按 session 拉全量，
   按 query 文本 + 时间窗口模糊匹配，认得出来就当作成功。
4. 确认为终态后从 journal 移除。

工具描述里必须写清："拿到 dispatched_unknown 时，
先调 get_answer 确认结果，不要重复 ask。"

### 决策四：正文解析做双通道

**通道 A：artifact 解析**
从 `templateData.text` 正则抓 `AgentEventRenderer.render({...})`，
取 `turn/finalResponse/delta` 的 `delta` 拼接，剥掉标签得到正文。
纯 HTTP 可完整还原，不需要浏览器。

**通道 B：cot 解析**
从 `templateData.cot` 两层 JSON 解析，取过程话术 `item/agentMessage/delta`
和工具标题 `item/tool/start` 的 `display.title`。

A 拿最终结论，B 拿执行轨迹。两个都要暴露。

**解析器必须对未知事件宽容。** `AgentEventRenderer` 是事件流不是固定模板，
上游新增 method 是常态。规则：

- 未知 method **忽略并计数**，不抛异常
- 只有当"已知 method 全部缺失"时才抛 ContractError
- 事件流里出现未知方法时，结果附 `warnings: ["unknown events: item/xxx"]`

否则上游每加一个字段，整个工具就全挂，与稳定性优先相悖。

### 决策四之补：断言分级，防止静默降级

ContractError 只能拦住"结构变了"。有一类更隐蔽的情况它拦不住：
**结构没变，但关键内容空了。** 比如 `cot` 还在，
但 `item/tool/start` 不再出现，工具轨迹就静默变成空数组。

而工具轨迹恰好是本工具的核心卖点之一。

所以解析结果分三档：

| 情况 | 处理 |
|---|---|
| 必填结构缺失 | 抛 ContractError，附原始片段 |
| 结构在但语义可疑 | 正常返回，加 `warnings` |
| 一切正常 | `warnings: []` |

具体的可疑判定：
- `cot` 存在但零个工具事件，且正文提到"查""读"等动作词
- 正文长度 < 50 字符但有工具轨迹
- 出现未知事件类型

`warnings` 通过 MCP 的 `structuredContent` 返回，成本很低，
能防止 agent 把残缺结论当完整结论用。

### 决策五：不加 SQLite，但留 MessageSink 接口

用户明确要求不加本地库，理由是容易不同步。这个判断成立。

设计上用一个接口隔离。接口要**幂等**，否则将来实现 SQLite 时
`get_transcript` 和 `get_answer` 会重复写入同一条：

```python
class MessageSink(Protocol):
    def upsert_turn(
        self,
        session_id: str,
        turn: Turn,
        source: Literal["transcript", "answer"],
    ) -> None: ...

class NullSink:
    def upsert_turn(self, session_id, turn, source): pass
```

去重依据是 `(session_id, turn.query_id)`。`Turn` 必须带稳定的 `query_id`。
这样将来加 FTS5 全文检索，实现这个接口即可，上层零改动。

### 决策六：cookie 管理要有事前预判

cookie 是唯一入口的钥匙，失效时工具完全不可用。

存放位置 `~/.config/lingguang/credentials.json`，Windows 下用 DPAPI 加密，
或者退一步至少 0600 权限。**明文 ctoken 被同步盘扫走等于泄露支付宝授权登录态。**

记录三个时间戳：

```json
{
  "cookie": "...",           // 加密存储
  "imported_at": "...",
  "last_ok_at": "...",       // 每次请求成功刷新
  "last_error": "...",       // 最近一次失败原因
  "last_error_at": "..."
}
```

`auth_status` 返回"已导入 N 天，上次成功 M 小时前"，是事前预判而非事后诊断。

`auth import` 要支持两种输入：整段 cookie 字符串、curl 命令原文。
导入后立即调一次 `loginCheck` 验证，失败立刻报错，不要等下次用才炸。

**错误归类规则**：曾经成功过但目前连续失败，
优先判为 `AuthError` 而非 `ContractError`，避免误导排查方向。

### 决策七：限流，按人级低频设计

这个接口是面向浏览器前端的，蚂蚁侧有 jshield / apdid 风控。
高频轮询会让账号被标记，而那会连带影响用户在 App 里正常使用灵光。

规则：

- `get_answer` 轮询首次 3 秒，之后指数退避到 5 至 8 秒
- 用户级串行，不做并发批量
- CLI 的批量场景显式串行并加间隔
- README 里写清"本工具设计为低频人级调用，不要拿来做爬虫"

### 决策八：解析失败时数据仍可取

这是"唯一入口"场景最重要的兜底。

即使解析器全挂，历史接口返回的原始 JSON 本身仍有归档价值。
必须保证这条路径存在：

- `export --format raw` 输出未经解析的原始响应
- `ContractError` 触发时把原始响应体写到 `~/.cache/lingguang/failed/`
- `doctor` 把"上游版本变化且 fixture 跑不通"标为 failed，
  `serve` 在这种情况下拒绝启动并说明原因

**静默返回错误答案比拒绝服务更糟。**

### 决策九：APASS 高危确认目前不可测，但必须预留

灵光 2.0 于 2026-10-27 发布，接入蚂蚁 APASS，官方说法是
"高危操作需用户确认"。但实测三条线索都指向**该能力在网页端尚未实现**：

1. 网页端 21 个脚本里搜 `apass`、`apAuth`、`riskControl`、`高危`、
   `二次确认`、`approval`，零命中
2. 两个会话的完整 cot 里 method 全集只有九种，全是常规 Agent 生命周期，
   没有 confirm / approval / interrupt / user_action 类事件
3. `item/tool/start` 的 params 只有 `itemId`、`groupId`、`display.title`，
   没有 `riskLevel` 或 `requiresConfirm` 字段

判断：功能太新，还没落地到网页端，或者只在 App 原生层实现。

**但这对封装工具是真实风险**：如果未来某次查询触发了确认，
而 HTTP 层拿不到那个信号，`get_answer` 会永远停在 pending，
调用方误以为任务卡死。

所以 `get_answer` 的超时必须分两种情况：

```
超时，且该轮从未出现过        -> task_timeout
        可能任务失败或未受理

超时，但该轮出现过、无正文     -> awaiting_confirmation
        可能等待用户在 App 内人工确认
```

第二种要明确提示"这次提问可能需要你在灵光 App 里手动确认"。

另外预留一个钩子：决策四的解析器对未知事件宽容，
一旦上游开始推送确认类事件，会被自动识别进 `warnings`，
不会静默丢弃。这条设计顺便把未来兼容性接上了。

---

## 四、MCP 工具设计：6 个

按最新规范（2026-07-28）：
- `inputSchema` 必须是非 null 的合法 JSON Schema
- 无参数时用 `{"type":"object","additionalProperties":false}`
- 提供了 `outputSchema` 就必须返回符合它的 `structuredContent`
- 返回结构化数据时**同时**给 TextContent 文本块做兼容
- `annotations` 默认不可信，不依赖它做安全判断

### 1. `list_sessions`

```
参数: limit (int, 默认 30, 上限 30), cursor (str|null), scene (str, 默认 LEOPARD)
返回: { sessions: [{id, summary, scene, created_at, updated_at}], next_cursor }
```

`latestTime` 做游标，`hasMore` 为 false 时 `next_cursor` 返回 null。
游标由调用方持有，服务端不记状态。

### 2. `get_transcript`

```
参数: session_id (必填), limit (默认 30), keyword (可选)
返回: { turns: [{role, text, tools: [str], summary, query_id, created_at}] }
```

`keyword` 在内存过滤，不额外打接口。
`tools` 是字符串数组，扁平结构方便模型直接读。
调用时顺手把结果写入 sink（默认 NullSink 无动作）。

### 3. `ask`

```
参数: query (必填), session_id (可选)
返回: { session_id, query_id, status: submitted|dispatched_unknown }
```

**`session_id` 不传时自动新建**：客户端生成 UUID，
服务端直接采用，返回新建的 id。

描述里必须写明两件事：
- "立即返回，需配合 get_answer 取结果"
- "拿到 dispatched_unknown 时先查 get_answer，不要重复 ask"

### 4. `get_answer`

```
参数: query_id (必填), session_id (可选), wait_seconds (默认 0, 上限 60)
返回: { status: pending|dispatched_unknown|done, text, tools: [str], warnings: [str] }
```

`status` 三态：
- `pending`：还没出现，继续等
- `dispatched_unknown`：SSE 断流，结果未知，需要再查
- `done`：拿到结果

`session_id` 可选，因为 `query_id` 已全局唯一。
只有走模糊匹配恢复时才需要 `session_id`。

`wait_seconds=0` 立即查一次。`>0` 轮询到出结果或超时，超时明确报错。
轮询间隔首次 3 秒，之后指数退避到 5 至 8 秒。

如果客户端支持 progress，轮询期间每 5 秒发一次 progress，
避免客户端显示卡死。

### 5. `auth_status`

```
参数: 无
返回: { valid, session_count, scene, hint }
```

让模型能自己诊断登录态。cookie 失效时直接告诉用户重新导入，
不要让人猜为什么失败。

### 6. `delete_session`

```
参数: session_id (必填), confirm (bool, 必填)
返回: { deleted: bool, session_id }
```

破坏性操作。CLI 和 MCP 统一提供，不做两套。

安全设计：
- `confirm` 必须显式为 `true`，否则直接报错不做任何事
- 工具 `annotations` 标 `destructiveHint: true`、`idempotentHint: true`
- 描述里写清"删除后不可恢复，删除前先用 get_transcript 确认目标"
- 接口本身幂等，删不存在的 id 也返回成功，不用担心重复调用

`confirm` 参数是对模型的一道护栏，让它必须意识到这是破坏性动作。
真正的最后防线是工具描述，不是参数。

### 不做的事

- **不做 sync**。无状态设计下不需要
- **不做 search_archive**。没有本地库

CLI 与 MCP 能力对齐，唯一差别是 CLI 多了 `doctor`、`export`、`auth import` 这类运维命令。
`delete` 两边都有，签名一致。

---

## 五、CLI 设计

命令树对齐 MCP，多出运维命令：

```
lingguang
  auth      status | import <file> | clear
  sessions  list [--limit N] | show <id> [--keyword KW]
  ask       "问题" [--session ID] [--wait] [--timeout S] [--json]
  answer    <query-id> [--session ID] [--wait S] [--json]
  export    <session> --format md|json|jsonl|raw -o FILE
  delete    <session-id> --yes
  serve                         # 启动 MCP stdio server
  doctor                        # 环境自检
```

`answer` 是 `get_answer` 的 CLI 对应物，不叫 `get-answer` 是为了少打字。

两个原则：

**输出要可管道**。默认人类可读，`--json` 输出机器可读。

**`doctor` 不能省**。检查项：cookie 是否存在可解析、登录态是否有效、
接口连通性、解析器能否跑通 fixture。这类逆向工具最怕静默失败。

---

## 六、健壮性设计

### 错误分类

```python
class LingguangError(Exception): ...
class AuthError(LingguangError):      # cookie 失效，提示重新导入
class RateLimitError(LingguangError): # 退避重试
class ContractError(LingguangError):  # 接口结构变了，带原始样本
class TransportError(LingguangError): # 网络问题，重试
```

**`ContractError` 是这类工具的生命线。** 所有解析器在结构不符时抛它，
带原始样本片段。接口一改立刻定位，不会静默返回空数据。

### 重试策略

只对幂等操作和传输错误重试。
提问接口**不重试**（会重复发送）。删除接口幂等可以重试。

### 版本探测

每次启动记录 `appInfo.version`，变了就在 stderr 提示
"上游版本变化，注意解析兼容性"。当前是 `v1.0.56`。

---

## 七、测试策略

**第一层：解析器单测**
用真实 artifact HTML 当 fixture。

fixture 处理原则：**尽量原样保留，只做字面替换**。
标签结构、类名、delta 的分段方式本身就携带上游版本信息，
顺手重排缩进或换行会让 fixture 失去回归价值。

把"脱敏后的原始字节"和"解析后的期望值"分开存：
- `fixtures/answer_billing.raw.html`：只替换金额、商户名为占位符
- `fixtures/answer_billing.expected.json`：期望的正文和工具标题

覆盖五种情况：纯文本回复、长账单报告、带工具轨迹、空轨迹、含未知事件类型。

**第二层：契约测试**
打真实接口，只断言结构不断言内容。需要 cookie，`--live` 标记，默认跳过。

**第三层：新建会话回归**
专门测 `ask` 不带 session_id 能否建出会话。这是关键能力，容易因接口变动失效。

**第三层必须不污染真实数据**：测试提问加 `[e2e-test]` 前缀，
测试结束自动调删除接口清理。删除接口幂等，成本很低。

**第四层：断流恢复**
模拟 SSE 中途断开，断言返回 `dispatched_unknown` 而非异常，
且 `get_answer` 能通过 journal 恢复出结果。

---

## 八、实施顺序与提交点

每一步单独 commit。

1. **项目骨架**：`pyproject.toml`(uv)、`.gitignore`、README -> `chore: 初始化项目骨架`
2. **解析器 + fixture 测试**（最关键）-> `feat: artifact 与 cot 双通道解析器`
3. **传输层 + 业务层**：`client.py`、`service.py`、`sink.py` -> `feat: HTTP 客户端与业务编排`
4. **认证与错误分类** -> `feat: 认证管理与错误分类`
5. **CLI** -> `feat: CLI 命令集`
6. **MCP server** -> `feat: MCP stdio server`
7. **文档**：`docs/reverse-notes.md` 记录全部接口细节 -> `docs: 接口逆向记录`

先做解析器和 core，MCP 是最薄的一层放最后。

---

## 九、明确不做的事

- **不做自动登录**。支付宝/钉钉扫码无法绕过，cookie 手动导入一次
- **不做对话内多轮编排**。Agent 自己会多轮调工具，外面再包是重复劳动
- **不做写入类操作**（发消息、改配置）。工具只读不写
- **不做 Web UI**
- **不做 SQLite**。留 MessageSink 接口，将来需要再加

---

## 十、目录布局

```
lingguang-mcp/
  pyproject.toml
  README.md
  .gitignore
  src/lingguang/
    __init__.py
    core/            # 纯业务，cli 与 mcp 只能通过这里访问
      errors.py
      models.py
      parser.py
      client.py
      service.py
      sink.py
      auth.py
    cli/ (main.py commands.py)
    mcp/ (server.py tools.py)
  tests/
    fixtures/ (脱敏后的真实样本 + 期望值)
    test_parser.py
    test_contract.py
  docs/
    reverse-notes.md
```

**分层约束写进 README**：`cli/` 和 `mcp/` 只准 import `core` 下的
`service`、`models`、`errors`，不准直接碰 `client` 和 `parser`。
这样维护者能一眼看出哪些是稳定接口。

`docs/reverse-notes.md` 单独维护，记录每个接口的发现时间、
请求体样例、已知坑。半年后回看，这份文档比代码更有价值。

---

## 十一、接口速查

```
POST /chat/stream_chat                       提问（SSE），sceneCode=WEB
POST /chat/queryHistoryChatSession.json      会话列表，sceneCode=LEOPARD
POST /chat/queryHistoryChatContent.json      对话全文，pageSize<=30
POST /chat/deleteChatSession.json            删除会话，幂等
GET  /channel/getAuthToken.json              WS 通道凭据
POST /user/loginCheck.json                   登录态
POST /user/queryUserInfo.json                用户信息
```

鉴权：cookie 里的 `ctoken`。关键 cookie 有 `ctoken`、
`prod_LINGGUANGJSESSIONID`、`spanner`。

跨站请求时注意 CORS 只放行 `https://www.lingguang.com`，
服务端调用要带 `Origin` 和 `Referer` 头。
