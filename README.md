<div align="center">

# lingguang-mcp

**把灵光 AI 的支付宝账单查询能力，封装成 MCP 工具和 CLI**

让 AI Agent 替你向灵光提问、取回结论、记录 Agent 的执行轨迹

间接实现查询支付宝账单等能力

![Python](https://img.shields.io/badge/python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white) ![MCP](https://img.shields.io/badge/MCP-2026--07--28-6E56CF?style=flat-square) ![License](https://img.shields.io/badge/license-MIT-yellow?style=flat-square)

![PyPI](https://img.shields.io/badge/PyPI-lingguang-3775A9?style=flat-square&logo=pypi&logoColor=white) ![CLI](https://img.shields.io/badge/interface-CLI%20%2B%20MCP-FF6B35?style=flat-square) ![Transport](https://img.shields.io/badge/transport-stdio-2E8B57?style=flat-square) ![Tests](https://img.shields.io/badge/tests-54%20passed-4CAF50?style=flat-square)

</div>

> 本项目基于对 `lingguang.com` 网页接口的逆向分析，非官方 SDK。
> 接口随时可能变动，使用前请阅读 [风险与边界](#风险与边界)。

**不想自己折腾配置？** 复制以下内容发给 AGENT 工具。

```
请帮我装好 lingguang，这是一个让我能通过你查询支付宝和钉钉消息的工具。
需要两步：
1. 装工具：uv tool install lingguang
2. 装 skill：npx skills add Tokisaki-Galaxy/lingguang-mcp -g -y
仓库地址：https://github.com/Tokisaki-Galaxy/lingguang-mcp
详细说明见随附的 USAGE.md。
```

> 如果你是一个LLM,请阅读与当前文件同级的USAGE.MD文件帮助用户快速配置

## 为什么需要它

支付宝账单和钉钉消息，对个人用户没有可用的开放接口：

- 支付宝不向个人开放账单 API
- 钉钉需要企业管理员开启数据访问权限

灵光是唯一入口。它拿到支付宝授权、连上钉钉之后，能通过 Agent 真实查询账单。

## 前提：先连好服务

**刚注册的灵光是普通 AI，查不了账单。** 必须先做这两件事：

- 在**手机灵光 App** 里连接支付宝，完成授权
- 其他集成类似，均需要先在手机 App 里授权一次

**这些连接动作只能在实际的手机 App 里做**，网页版和本工具都没有连接入口。

没连的情况下，本工具能正常提问，但灵光会回答没有数据。

所以本项目本质上是一个**遥控器加录音机**：替你的 Agent 向灵光提问、取回结论、记录 Agent 的执行轨迹。

## 两种使用方式

本项目同时提供 **CLI** 和 **MCP** 两套接口，共用同一套核心逻辑，能力完全对齐。

| | CLI | MCP |
|---|---|---|
| 适合 | 人工手动操作、脚本调用、排查问题 | AI Agent 自动调用 |
| 启动 | `lingguang <命令>` | `lingguang serve` |
| 传输 | 进程内 | stdio |
| 能用的工具 | 全部，另有 `doctor` / `export` / `auth` 等运维命令 | 6 个基础工具 |
| 删除会话 | `lingguang sessions delete <id> --yes` | `delete_session`（需 `confirm=true`） |

两边签名一致，行为一致。按照现在最佳工程实践，推荐使用CLI+SKILLS。

## 安装

两步：先装工具，再装 skill。两个都要，缺一个用不了。

### 第一步：装工具

```bash
uv tool install lingguang
```

装完 `lingguang` 命令在任何目录都可用。升级重跑这条命令，卸载用 `uv tool uninstall lingguang`。

没有 `uv` 的话先装（Python 的现代包管理器，比 pip 快得多）：

```bash
# Windows PowerShell
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# Linux / macOS
curl -LsSf https://astral.sh/uv/install.sh | sh
```

用 pip 也能装，但需要自己管虚拟环境：

```bash
pip install lingguang
```

### 第二步：装 skill

skill 是一份写给 AI 助手看的操作手册，告诉它什么时候该查账单、怎么用这些命令。

```bash
npx skills add Tokisaki-Galaxy/lingguang-mcp -g -a opencode -y
```

装到 `~/.agents/skills/lingguang/`。重启 opencode 生效。

其他 AI 工具把 `-a opencode` 换成对应的名字即可，比如 `-a claude-code`。

**备选：用 GitHub CLI 安装**

已经装了 `gh` 的话，也可以这样装：

```bash
gh skill install Tokisaki-Galaxy/lingguang-mcp --agent opencode --scope user
```

效果一样，装到同一位置。但注意 `gh skill` 目前还是 preview 功能，
命令和行为可能变动。两者选一个就行，不要重复装。

**为什么要装 skill？** 工具本身只是命令，AI 不会自己知道什么时候该用、该怎么用。
skill 补上这层判断。不装也能用，但你得自己记住每条命令。

### 从 Git 安装（追最新代码）

想在正式发版前拿到未发布的改动：

```bash
uv tool install git+https://github.com/Tokisaki-Galaxy/lingguang-mcp.git
```

指定分支或版本：

```bash
uv tool install git+https://github.com/Tokisaki-Galaxy/lingguang-mcp.git@master
uv tool install git+https://github.com/Tokisaki-Galaxy/lingguang-mcp.git@v0.1.0
```

skill 也一样，把仓库地址换成 git URL 即可。

### 参与开发

```bash
git clone https://github.com/Tokisaki-Galaxy/lingguang-mcp
cd lingguang-mcp
uv sync --extra dev
```

在项目目录里用 `uv run lingguang <命令>` 跑，或者激活虚拟环境后直接用 `lingguang`。

## 获取 cookie

这是唯一需要手动做的一步。cookie 相当于账号登录凭证，
程序没法替你登录，因为灵光要扫码。

### 步骤

1. 用浏览器打开 https://www.lingguang.com 并登录

2. 按 `F12` 打开开发者工具，切换到 **Application** 标签
   （中文版 Chrome 或 Edge 里叫「应用」）

3. 左侧栏找到 **Storage → Cookies → https://www.lingguang.com**

4. 在右侧表格里找到这三个值，双击 Value 列复制：

   | Cookie 名 | 说明 | 是否必须 |
   |---|---|---|
   | `ctoken` | 会话标识，形如 `bigfish_ctoken_xxx` | 必须 |
   | `prod_LINGGUANGJSESSIONID` | 服务端会话 | 强烈建议 |
   | `spanner` | 网关会话 | 强烈建议 |

   `spanner` 的域名是 `cognihome.lingguang.com`。
   如果在上面的列表里找不到，检查左侧有没有 `cognihome.lingguang.com` 这一项。

5. 把它们拼成一行，用分号加空格分隔：

   ```
   ctoken=bigfish_ctoken_xxxxx; prod_LINGGUANGJSESSIONID=prod_yyyyy; spanner=zzzzz
   ```

6. 存成文件，比如项目根目录下的 `cookie.txt`

### 最容易踩的坑

`prod_LINGGUANGJSESSIONID` 是 **HttpOnly** 的，
在控制台敲 `document.cookie` 读不到，必须在 Application 面板里复制。

### 导入并验证

```bash
lingguang auth import cookie.txt
```

导入后会立刻验证一次。成功会显示：

```
已保存到Windows 凭据管理器
验证通过，cookie 可用
```

**cookie 存在哪里：**

- **Windows**：系统凭据管理器，标识 `lingguang-mcp`，
  可在「控制面板 → 凭据管理器 → Windows 凭据」里查看和删除。
  不存在用户目录里，同步盘扫不到。
- **Linux / macOS**：`~/.config/lingguang/credentials.json`，权限 0600。

失败会直接报错，不会等到下次用的时候才炸。

也可以用环境变量跳过文件：

```bash
# Windows PowerShell
$env:LG_COOKIE="ctoken=xxx; spanner=yyy"

# Linux / macOS
export LG_COOKIE="ctoken=xxx; spanner=yyy"
```

## 自检

```bash
lingguang doctor
```

三项都通过就可以用了：

```
[通过] cookie 齐全
[通过] loginCheck 成功
[通过] 解析器能提取正文（891 字符）
```

## 检查版本与更新

```bash
lingguang version
```

这是唯一会访问 PyPI 的命令，用来检查有没有新版本：

```
lingguang 0.3.0
最新版本 0.4.0，有新版本可升

  升级：uv tool upgrade lingguang
  改了什么：https://github.com/Tokisaki-Galaxy/lingguang-mcp/compare/v0.3.0...v0.4.0

Python 3.11.11
凭据存储 windows-credential-manager
凭据状态 有效，上次成功 2 小时前
```

只想要版本号、不联网：

```bash
lingguang --version      # 输出 0.3.0
lingguang version --offline
```

**除了查灵光数据，这是唯一会访问外部服务的命令。**
其他命令只会连灵光接口，不会连别的任何地方。

## CLI 用法

```bash
# 列出会话
lingguang sessions list

# 查看某个会话，带工具执行轨迹
lingguang sessions show <session-id> --tools

# 提问并等待结果
lingguang ask "这个月吃饭花了多少钱" --wait

# 只提交不等待，拿 query_id
lingguang ask "这个月吃饭花了多少钱"
lingguang answer <query-id> --wait 40

# 导出归档
lingguang export <session-id> --format md -o out.md
```

完整命令：

| 命令 | 用途 |
|---|---|
| `lingguang auth status` | 检查登录态 |
| `lingguang auth import <文件>` | 导入 cookie |
| `lingguang auth clear` | 清除本地 cookie |
| `lingguang sessions list` | 列出会话 |
| `lingguang sessions show <id> [--tools] [--keyword KW]` | 查看会话内容 |
| `lingguang sessions delete <id> --yes` | 删除会话 |
| `lingguang ask "问题" [--wait] [--timeout N]` | 提问 |
| `lingguang answer <query-id> [--wait N]` | 取回提问结果 |
| `lingguang export <id> --format md\|json\|jsonl\|raw` | 导出会话 |
| `lingguang doctor` | 环境自检 |
| `lingguang version` | 检查版本更新（访问 PyPI） |
| `lingguang serve` | 启动 MCP server |

所有查询命令都支持 `--json`，方便管道处理。

## MCP 用法

### 挂载

编辑 opencode 配置文件：

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

如果用 `uv tool install` 装的，`lingguang` 已经在 PATH 里，
上面的配置直接用就行。

如果没装到 PATH，用 `uv run` 指向项目目录，跨平台通用：

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

Linux 或 macOS 把路径换成 `/path/to/lingguang-mcp` 即可。

### 提供的工具

| 工具 | 用途 |
|---|---|
| `list_sessions` | 列出会话，支持游标分页 |
| `get_transcript` | 读取会话正文与 Agent 工具执行轨迹 |
| `ask` | 提交提问，立即返回，不阻塞 |
| `get_answer` | 取回提问结果，可短暂轮询 |
| `auth_status` | 检查登录态 |
| `delete_session` | 删除会话，必须显式传 `confirm=true` |

### 为什么提问是两段式

账单分析要跑 20 到 30 秒。MCP 工具同步阻塞会撞客户端超时，
调用方也没法中途取消。所以拆成：

```
ask        -> 立即返回 { session_id, query_id }
get_answer -> 按 query_id 取结果，wait_seconds 最多等 60 秒
```

Agent 的自然用法是 `ask` 之后立刻 `get_answer(wait_seconds=40)` 等结果。

### 工具轨迹是核心价值

每轮回答都能拿到 Agent 真实调用的子程序列表：

```
查看账单查询服务目录 / 统计本月收支概况 / 分析近三个月账单趋势 / 统计本月分类消费构成
```

这是普通对话接口给不了的结构化信息。

## 技术栈

| 层 | 选型 | 说明 |
|---|---|---|
| 语言 | Python 3.11+ | 用 `uv` 管理依赖 |
| HTTP | `requests` | SSE 按字节流自定义切帧，不用 `iter_lines` |
| MCP | 规范 `2026-07-28` | stdio 传输，无协议级会话 |
| CLI | `typer` | 自动生成帮助，支持 `--json` 管道输出 |
| 测试 | `pytest` | 54 项单测 + 5 项契约测试 |
| 存储 | 无 | 默认不落库，留 `MessageSink` 接口做扩展点 |

架构分三层，`cli/` 和 `mcp/` 是 `core/` 的薄壳：

```
src/lingguang/
  core/     解析器、HTTP 客户端、业务编排、异常分类
  cli/      命令行入口
  mcp/      MCP stdio server 与工具定义
```

## 风险与边界

**不是官方工具，接口随时可能失效。**

本项目依赖逆向出的网页接口。上游改版时解析器会崩。`lingguang doctor` 能帮你发现，但不能替你修。解析全挂时用 `export --format raw` 拿原始 JSON 兜底。

**请保持低频使用。**

这是最重要的一条。蚂蚁侧有风控系统，本工具按「个人日常使用」的频率设计。不要用它做批量抓取、定时轮询或自动化脚本。高频请求会让账号被风控标记，后果会连带影响你在灵光 App 里的正常使用。

正常节奏参考：一天问几次，和你在 App 里用的频率保持一致。

**cookie 等于你的登录态。**

`ctoken` 泄露等于别人能以你的身份访问灵光，看到你的账单。
不要把 `cookie.txt` 分享给任何人，不要提交到仓库。
Windows 上 cookie 存在系统凭据管理器，不在用户目录，同步盘扫不到。
Linux / macOS 存在 `credentials.json`，`.gitignore` 已排除。

cookie 会在长时间不操作后失效。失效时重新导入即可，`lingguang auth status` 会告诉你上次成功是多久之前。

**数据保存在哪里。**

除了 cookie，本工具不保存任何历史数据。默认不落库，每次调用都实时拉取。
需要归档时用 `lingguang export` 导出到你自己选的位置。

**关于 APASS 高危确认。**

灵光 2.0 宣称接入蚂蚁 APASS，高危操作需用户确认。
但实测表明该能力尚未在网页端落地。
如果未来某次提问触发了确认，`get_answer` 会返回
`awaiting_confirmation` 状态，此时需要你在灵光 App 里手动确认。

## 开发

```bash
# 跑测试
uv run pytest

# 含真实接口的契约测试（需要先导入 cookie）
uv run pytest -m live
```

约束：`cli/` 和 `mcp/` 只准 import `core` 下的
`service`、`models`、`errors`，不直接碰 `client` 和 `parser`。

接口逆向的完整记录，包括九条实测约束和已知坑，
见 [docs/reverse-notes.md](docs/reverse-notes.md)。

给 AI 助手看的使用说明见 [USAGE.md](USAGE.md)。

---

## 许可

MIT。详见 [LICENSE](LICENSE)。

本项目仅供个人学习与自用。使用者需自行承担因使用本项目产生的包括但不限于账号受限、数据丢失在内的风险。项目作者不对因使用本项目造成的任何后果负责。
