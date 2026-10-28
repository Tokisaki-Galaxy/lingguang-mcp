# HOT TO USE

## 转发模板

复制下面这段发给你所使用的AGENT工具。

```
请帮我装好 lingguang，这是一个让我能通过你查询支付宝账单和钉钉消息的工具。
需要两步：
1. 装工具：uv tool install lingguang
2. 装 skill：npx skills add Tokisaki-Galaxy/lingguang-mcp -g -a opencode -y
仓库地址：https://github.com/Tokisaki-Galaxy/lingguang-mcp
详细说明见随附的 USAGE.md。
```

以下内容写给 AI 助手。

## 你的任务

用户想通过你调用灵光 AI 的能力，主要是查支付宝账单和钉钉消息。
这两个能力对个人没有开放 API，灵光是唯一入口。

你的工作是帮用户把 `lingguang` 装好，然后教会他怎么用。

## 第一步：装工具

先检查用户有没有 `uv`：

```bash
uv --version
```

**没有就先装**

```bash
# Windows PowerShell
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# Linux / macOS
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**然后安装本工具**。已经发布到 PyPI，一条命令就够，不需要 clone：

```bash
uv tool install lingguang
```

装完后 `lingguang` 命令在任何目录都可用。

用户想追最新未发布代码的话，从 git 装：

```bash
uv tool install git+https://github.com/Tokisaki-Galaxy/lingguang-mcp.git
```

如果用户想改代码、参与开发，用 clone 方式：

```bash
git clone https://github.com/Tokisaki-Galaxy/lingguang-mcp
cd lingguang-mcp
uv sync --extra dev
```

这种情况要在项目目录里用 `uv run lingguang <命令>`。

装完验证：

```bash
lingguang --help
```

## 第二步：帮用户获取 cookie

**这一步必须用户亲自做，你没法代劳**，因为灵光要扫码登录。

请你把下面这些步骤清楚地转告用户，不要只说"去弄个 cookie"：

### 告诉用户的话术

> 接下来需要你手动拿一下登录凭证，大概两分钟：
>
> 1. 用浏览器打开 https://www.lingguang.com 并登录
> 2. 按 F12 打开开发者工具，切到 **Application** 标签（中文版叫「应用」）
> 3. 左侧找到 **Storage → Cookies → https://www.lingguang.com**
> 4. 右边表格里找这三个，双击 Value 列复制：
>    - `ctoken`
>    - `prod_LINGGUANGJSESSIONID`
>    - `spanner`
> 5. 拼成一行，分号加空格隔开，像这样：
>    `ctoken=bigfish_ctoken_xxx; prod_LINGGUANGJSESSIONID=prod_yyy; spanner=zzz`
> 6. 存成文件，比如 `cookie.txt`
> 7. 跑：`lingguang auth import cookie.txt`

### 提醒用户注意两件事

**`spanner` 在另一个域名下。** 如果第 3 步的列表里没有它，
让用户找左侧的 `cognihome.lingguang.com` 那一项。

**别在控制台敲 `document.cookie`。** `prod_LINGGUANGJSESSIONID` 是 HttpOnly 的，
JS 读不到，必须在面板里复制。这是最容易踩的坑。

### 验证导入结果

用户导入后，你跑一下：

```bash
lingguang auth status
```

看到 `"valid": true` 和 `"probe": "loginCheck 通过"` 就算成功。

---

## 第三步：挂载 MCP

编辑用户的 opencode 配置文件，加入：

```json
{
  "mcp": {
    "lingguang": {
      "type": "local",
      "command": ["lingguang", "serve"],
      "enabled": true
    }
  }
}
```

如果是用 `uv tool install` 装的，`lingguang` 已经在 PATH 里，上面的配置直接用。

如果不在 PATH 里，或者用户是 clone 下来的，用 `uv run` 指向项目目录，
这个写法跨平台通用：

```json
{
  "mcp": {
    "lingguang": {
      "type": "local",
      "command": [
        "uv", "run",
        "--directory", "C:\\path\\to\\lingguang-mcp",
        "lingguang", "serve"
      ]
    }
  }
}
```

Linux 或 macOS 把路径换成 `/path/to/lingguang-mcp`。

**不要写 `.venv\\Scripts\\lingguang.exe` 这种路径。**
那是 Windows 专用，换个平台就失效。用上面的 `uv run` 写法。

挂载后跑一次自检：

```bash
lingguang doctor
```

三项全通过：

```
[通过] cookie 齐全
[通过] loginCheck 成功
[通过] 解析器能提取正文（891 字符）
```

## 第四步：告诉用户怎么用

装好之后，用户直接对你说人话就行，比如：

- "这个月我吃饭花了多少钱"
- "帮我看看 9 月的账单里有哪些大额支出"
- "我之前问过灵光什么"
- "把上次那个账单分析导出来存一份"

你负责翻译成工具调用。

## 你调用工具时的规则

### 提问是两段式

```
ask(query)                          -> { session_id, query_id }   立即返回
get_answer(query_id, wait_seconds)  -> { status, text, tools }    取结果
```

账单类问题要跑 20 到 30 秒。**不要在 ask 里干等。**

标准做法：

```
1. ask("这个月吃饭花了多少")
2. get_answer(query_id, wait_seconds=40)
```

`wait_seconds` 上限 60。

### `dispatched_unknown` 不是失败

`ask` 返回这个状态表示提问已经发出去了，但连接断了。

**绝对不要重发**，重发会导致账单被查两遍。
正确做法是调 `get_answer` 确认结果。

### get_answer 的四种状态

| status | 含义 | 怎么做 |
|---|---|---|
| `done` | 拿到结果 | 直接用 |
| `pending` | 还在跑 | 再等等，或告诉用户稍候 |
| `dispatched_unknown` | 已发出结果未知 | 继续查询，别重发 |
| `awaiting_confirmation` | 等人工确认 | 让用户去灵光 App 里点确认 |

### session_id 可以不传

`ask` 不传 `session_id` 会自动新建会话，返回值里带新的 id。

但**同一个话题请复用同一个 session_id**，否则历史会散成一堆。

### 删除会话要谨慎

```
delete_session(session_id, confirm=true)
```

调用前**先**用 `get_transcript` 确认删的是哪个，
把 summary 念给用户听，得到明确同意再删。删除不可恢复。

## 返回值长什么样

### get_answer

```json
{
  "status": "done",
  "text": "这个月吃饭花了 609.79 元...",
  "tools": ["刷新本月餐饮类支出统计"],
  "warnings": []
}
```

### get_transcript

```json
{
  "turns": [
    {
      "query": "用户问的",
      "answer": "灵光答的",
      "tools": ["工具标题1", "工具标题2"],
      "warnings": []
    }
  ],
  "count": 1
}
```

### tools 字段是核心价值

它记录了灵光真实调用了什么子程序：

```
["查看账单查询服务目录", "统计本月收支概况", "分析近三个月账单趋势"]
```

用户问"它是怎么算的"时，把这个给他看。

## 注意 warnings

`warnings` 非空说明结果可能不完整：

| warning 内容 | 含义 |
|---|---|
| `未知事件类型` | 灵光加了新东西，可能没解析全 |
| `cot 存在但未解析出工具事件` | 可能没真调工具 |
| `正文异常短但带工具轨迹` | 结果可能被截断 |
| `该轮已存在但无正文` | 可能在等人确认 |

**转述给用户，别吞掉。**

## 出错了怎么办

| 错误信息 | 原因 | 怎么做 |
|---|---|---|
| `cookie 可能已失效` | 登录过期 | 让用户重新导入 cookie |
| `被限流` | 请求太频繁 | 停一会，加大间隔 |
| `接口结构变了` | 灵光改版了 | 让用户跑 `doctor` |
| `删除未生效` | 上游改了删除逻辑 | 告诉用户这是 bug |

**认证类错误别重试**，重试一百次也没用。

## 必须提醒用户的三件事

### 别用太频繁

这个工具按"个人日常使用"设计。蚂蚁有风控，
高频请求会让账号被标记，**后果会连带影响用户在灵光 App 里的正常使用**。

- 一天问几次没问题
- 不要循环提问几十次
- 不要定时轮询
- 不要并发多个 ask

用户要批量处理时，先确认一下再动手。

### cookie 等于账号

`ctoken` 泄露等于别人能以用户身份看他的账单。
不要让用户把 cookie 贴到聊天里、发到群里、提交到仓库。

### 数据不落地

除了存 cookie，这个工具不保存任何历史。
需要归档时用 `lingguang export` 导出到用户指定的位置。

## 排查顺序

用户说不好使了，按这个来：

```
1. lingguang auth status          cookie 还有效吗
2. lingguang sessions list        接口通不通
3. lingguang sessions show <id>   解析器还能读吗
4. lingguang doctor               环境全面自检
```

如果列表能出来但内容全空，说明灵光改了数据格式，解析器需要更新。
