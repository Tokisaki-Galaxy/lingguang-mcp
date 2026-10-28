---
name: lingguang
description: 查询支付宝账单、消费统计、外卖与网购明细，或读取钉钉消息、归档灵光 AI 的历史对话。当用户问「这个月花了多少钱」「帮我分析账单」「外卖花了多少」「网购都买了什么」「钱花哪去了」「查我的钉钉消息」「之前问过灵光什么」「把账单导出」时使用。前提是用户的灵光账号已经在手机 App 里连好支付宝和钉钉，没连过会提示先连接。数据来自灵光 AI 已获得的授权，本 skill 只负责发问和取回结论，不直接访问账单原始数据。
---

# 灵光账单与钉钉查询

灵光 AI （阿里系）拿到用户的支付宝授权、连上钉钉之后，本 skill 通过其 CLI 代用户提问、取回结论、记录灵光 Agent 的执行轨迹。

**数据来自灵光，不是你算的。** 你无法直接访问账单原始数据，也没法查灵光没覆盖的账户。

## 前提：服务要先连好

**刚注册的灵光只是普通 AI。** 没连支付宝就查不到账单，没连钉钉就读不到消息。

**怎么判断：**

- 问「这个月吃饭花了多少」，回答里说没有账单数据，或 `tools` 为空
- `sessions show` 里工具轨迹只有「查看账单查询服务目录」这类空转动作

**先排除这个，再怀疑 cookie 和解析器。**

需要向用户解释原因、或给连接指引时，读 `references/service-setup.md`。

## 先确认命令可用

```bash
lingguang auth status
```
命令不存在时，说明工具没装：
```bash
uv tool install lingguang
```

## cookie 失效了怎么办

`auth status` 显示失效时，**读 `references/cookie-auth.md`**，里面有两种恢复方式的话术和完整步骤。

## 提一个问题
```bash
lingguang ask "这个月吃饭花了多少钱" --wait
```

`--wait` 阻塞等结果，账单类问题通常 30 秒。

**超过 60 秒没结果**，不要重复问，改成两段式：
```bash
lingguang ask "这个月吃饭花了多少钱"
# 输出：
# session: 5ee3aeb2-6013-47fd-b0ec-6e70c1741463
# query:   01a7d4a4-1108-4820-8459-2ebae44f0577

lingguang answer 01a7d4a4-1108-4820-8459-2ebae44f0577 --wait 40
```

**关键：`answer` 返回 `status: dispatched_unknown` 时绝对不要重新 ask。**
那表示提问已经发出去了，只是连接断了。重发会导致账单被查两遍。
继续用 `answer` 查询即可。

## 看 Agent 是怎么算的
```bash
lingguang sessions show <session-id> --tools
```

会多一行工具轨迹：

```
工具: 查看账单查询服务目录 / 统计本月收支概况 / 分析近三个月账单趋势 / 统计本月分类消费构成
```

用户问「它是怎么算出来的」时把这个给他看。
**这是本工具相对普通对话的核心价值。**

## 列出历史与导出
```bash
lingguang sessions list
lingguang export <session-id> --format md -o 账单分析.md
```

`--format` 可选 `md`、`json`、`jsonl`、`raw`。
解析出问题时用 `raw` 拿原始数据兜底。

## 状态码
| status | 含义 | 怎么做 |
|---|---|---|
| `done` | 拿到结果 | 直接用 |
| `pending` | 还在跑 | 再等一轮，或告诉用户稍候 |
| `dispatched_unknown` | 已发出但断线 | **继续 answer 查，不要重发** |
| `awaiting_confirmation` | 等人工确认 | 让用户去灵光 App 里点确认 |

## warnings 必须转述
结果里 `warnings` 非空时说明可能不完整：

| warning 内容 | 含义 |
|---|---|
| `未知事件类型` | 灵光加了新东西，可能没解析全 |
| `cot 存在但未解析出工具事件` | 可能没真调工具 |
| `正文异常短但带工具轨迹` | 结果可能被截断 |
| `artifact 存在但未提取到正文` | 渲染格式变了，解析器可能失效 |
| `该轮已存在但无正文` | 可能在等人确认 |

**告诉用户「这次结果可能不完整」**，不要吞掉。

## 三条必须遵守的规矩

### 没有工具轨迹就别给具体数字
如果一轮回答的 `tools` 是空的，说明 Agent 可能没真正查数据。
这时不要复述金额，要明说「这次没有查到实际工具调用，结果可能不可靠」。

### 保持低频
蚂蚁侧有风控。高频请求会让用户账号被标记。

### 不要把 cookie 写进任何输出
如果用户粘贴了 cookie，提醒他这是登录态，用完考虑重新登录换掉。

## 排查
```bash
lingguang doctor
```

如果「解析器能提取正文」那项失败，说明灵光改版了，需要更新工具。
如果 `sessions list` 能出列表但 `sessions show` 内容全空，也是同样的问题：解析器失效。
确认是项目问题后，在 https://github.com/Tokisaki-Galaxy/lingguang-mcp 上创建issue。

## 如果装了 MCP
MCP和CLI功能完全一致。
