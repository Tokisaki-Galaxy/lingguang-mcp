# 灵光接口逆向记录

## 一、基础信息

| 项 | 值 |
|---|---|
| API 域名 | `cognihome.lingguang.com` |
| 前端域名 | `www.lingguang.com` |
| 鉴权方式 | cookie 里的 `ctoken` |
| CORS 允许来源 | `https://www.lingguang.com` |
| 直连延迟 | 约 310ms，无需代理 |
| SSE 响应头 | `text/event-stream` |

关键 cookie 三个，缺任一都可能影响稳定性：

- `ctoken`：会话标识，形如 `bigfish_ctoken_xxx`
- `prod_LINGGUANGJSESSIONID`：JSESSION，服务端重启会变
- `spanner`：网关会话，域名在 `cognihome.lingguang.com`

---

## 二、接口清单

### 提问

```
POST /chat/stream_chat?ctoken=<token>
Content-Type: application/json
Accept: text/event-stream
```

请求体：

```json
{
  "query": "问题文本",
  "attachmentList": [],
  "extParams": {
    "clientTheme": "light",
    "appId": "202609150201453629925",
    "queryHint": "",
    "locationAuthStatus": "NOT_DETERMINED",
    "location": ""
  },
  "queryId": "<客户端生成的UUID>",
  "queryType": "text_input",
  "sessionId": "<客户端生成的UUID或已有会话id>",
  "sceneCode": "WEB"
}
```

### 会话列表

```
POST /chat/queryHistoryChatSession.json?ctoken=<token>

{"sceneCode":"LEOPARD","latestTime":null,"pageSize":30,"ctoken":"<token>"}
```

响应 `dataList` 每项：`sessionId`、`summary`、`sceneCode`、`createTime`、`updateTime`、`status`。

### 对话全文

```
POST /chat/queryHistoryChatContent.json?ctoken=<token>

{"sessionId":"<id>","sceneCode":"LEOPARD","latestTime":null,"pageSize":30,"ctoken":"<token>"}
```

### 删除会话

```
POST /chat/deleteChatSession.json?ctoken=<token>

{"sessionId":"<id>","sceneCode":"LEOPARD","ctoken":"<token>"}
```

### 其他

```
POST /user/loginCheck.json        {"ctoken":"<token>"}
POST /user/queryUserInfo.json
GET  /channel/getAuthToken.json?clientName=LEOPARD_WEB&channelType=SYNC
```

---

## 三、九条实测约束

### 1. sceneCode 分两套，不能统一

历史与删除用 `LEOPARD`，提问用 `WEB`。
代码里若统一传一个值，会有一半接口失败。

### 2. 可以新建会话，方式是客户端生成 UUID

之前误判为"无法新建"，因为传 `null`、空串、省略字段都 500。
实际做法是客户端自己生成 UUID 当 sessionId，服务端直接采用：

```
sessionId=""          -> 500
sessionId 省略         -> 500
sessionId=<新UUID>    -> 200，会话建出来
```

验证：生成 `93a11295-...` 发问，会话列表随即出现该 id，
标题自动取回复首句。

### 3. cross-scene 数据不隔离

`sceneCode=WEB` 与 `sceneCode=LEOPARD` 查询会话列表返回同一份数据。
场景字段只标识来源，不做隔离。

App 发起的会话是 `LEOPARD`，网页发起的是 `WEB`。

### 4. pageSize 上限 30

```
pageSize=30 -> OK
pageSize=31 -> SYSTEM_ERROR
```

超出直接报系统异常，不是参数错误，容易误判成服务故障。

### 5. SSE 不能用 iter_lines

单行 JSON 可能远超默认缓冲区，且含多字节 UTF-8。
用 `requests.iter_lines` 会截断并产生乱码（实测出现 `\x89`）。

必须按字节流累积，用 `\n\n` 切帧，再整体 `decode('utf-8')`。

### 6. 正文藏在 artifact 的脚本事件里

`templateData.text` 是一段完整的 HTML，正文以脚本形式内嵌：

```html
<script>AgentEventRenderer.render({"method":"turn/finalResponse/delta",
"params":{"delta":"\u003cp\u003e文本"},"timestamp":0});</script>
```

把所有 `turn/finalResponse/delta` 的 `delta` 拼接，
剥掉 HTML 标签即得明文。纯 HTTP 可还原，不需要浏览器渲染。

注意：`delta` 是逐段推送的，可能把一句话切成多段，
拼接后才是完整正文。

### 7. 轮次不会被半截查出

任务进行中，历史接口里根本没有这一轮。完成后一次性写入，
`status` 为 `VALID` 且正文完整。

实测：

```
t=3s   查到 0 条
t=4s   查到 1 条 status=VALID len=22641
```

所以 `get_answer` 只需判断"出现了没有"，不用判断"完不完整"。

### 8. 删除接口幂等

不存在的 session id 也返回 `{"code":"SUCCESS","success":true}`。
不用处理 404，也不用担心重复调用。

### 9. latestTime 游标是 best-effort

同一毫秒创建多个会话可能漏读，翻页过程中有新写入会漂移。
需要严格全量时用 `export --format raw` 全量拉取。

---

## 四、事件结构

### cot 里的方法（实测全集）

```
turn/start
item/agentMessage/start
item/agentMessage/delta
item/agentMessage/finish
item/toolgroup/start
item/tool/start
item/tool/finish
item/toolgroup/finish
turn/finish
```

工具调用事件的完整结构：

```json
{
  "method": "item/tool/start",
  "params": {
    "itemId": "item-3",
    "groupId": "group-1",
    "display": {"title": "查看账单查询服务目录"}
  },
  "timestampMs": "1793106222768"
}
```

只有 id、分组、标题。**没有风险等级，没有确认标记。**

### artifact 里的方法

```
turn/start
turn/finalResponse/start
turn/finalResponse/delta
turn/finalResponse/finish
turn/finish
```

### cot 是两层 JSON

外层是 `{"content": "<json字符串>"}`，`content` 里才是事件数组。
直接 `json.loads` 一次只能拿到字符串。

---

## 五、APASS 高危确认：文档有，实现没有

灵光 2.0 于 2026-10-27 发布，官方说明接入蚂蚁 APASS，
"将身份认证、意图安全和隐私保护纳入 Agent 执行流程"。

但实测三条线索都指向**该能力在网页端尚未落地**：

1. 网页端 21 个脚本里搜 `apass`、`apAuth`、`riskControl`、
   `高危`、`二次确认`、`approval`，零命中
2. 两个会话的完整 cot 里 method 全集只有九种，全是常规 Agent 生命周期，
   没有 confirm / approval / interrupt / user_action 类事件
3. `item/tool/start` 的 params 没有 `riskLevel` 或 `requiresConfirm` 字段

**判断**：功能太新，还没实现到网页端，或只在 App 原生层。

**对工具的影响**：如果未来触发确认而 HTTP 层拿不到信号，
`get_answer` 会一直 pending。所以状态里区分了
`pending`（从未出现）和 `awaiting_confirmation`（出现了但无正文）。

解析器对未知事件宽容，一旦上游开始推确认类事件，
会自动进 `warnings`，不会静默丢弃。

---

## 六、已知的解析边界

### cot 可能缺工具事件

实测有一个会话（`863db287`），问的是账单问题，
正文也提到了查询动作，但 `cot` 里零工具事件。

不是解析器的问题，是上游没写。所以解析器把这种情况判为
"结构在但内容可疑"，加 `warnings` 而不是抛错。

### 金额、商户名会被脱敏

fixture 里金额统一替换成 `00.00`，商户名换成"示例商户A"。
只做字面替换，不动结构。

有个例外：`claw_cot.1019.660990` 这类资源 URL 里的版本号会被
金额正则误伤，但它不是金额，无需处理。

---

## 七、复现方式

```bash
# 从浏览器导出 cookie 后
export LG_COOKIE="ctoken=xxx; prod_LINGGUANGJSESSIONID=xxx; spanner=xxx"

lingguang auth status
lingguang sessions list
lingguang sessions show <id> --tools
lingguang ask "测试问题" --wait
```

契约测试：

```bash
pytest -m live
```

---

## 八、如果上游改版，先看这几个地方

1. `parse_artifact_text` 是否还能提正文
2. `parse_cot_tools` 是否能拿到工具标题
3. `list_sessions` 的 `dataList` 字段名有没有变
4. `stream_chat` 返回的 SSE 帧格式

失败时 `ContractError` 会带原始样本片段，
原始响应会写到 `~/.cache/lingguang/failed/`。
