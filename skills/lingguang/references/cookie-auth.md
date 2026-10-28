# cookie 失效后的恢复

`lingguang auth status` 显示失效时读这份文件。

## 先跟用户说明，让他选

> 灵光的登录凭证过期了，需要重新登录一次。
> 有两种方式：
>
> **一、我帮你自动读。** 我开一个浏览器窗口，你在里面扫码登录，
> 登完我从浏览器里把凭证取出来。需要当前环境有 Playwright。
>
> **二、你自己复制。** 我给你步骤，你从浏览器开发者工具里复制几个值粘贴给我。
>
> 你要哪种？没有 Playwright 的话只能走第二种。

**等用户选，不要擅自开始读浏览器。** 这是读取登录凭证的操作，要让人知情。

## 方式一：用环境里的 Playwright 自动读

用户同意后，先确认有没有 Playwright 可用（MCP 工具，或本机装了
`playwright` / `playwright-core`）。有就走下面流程。

1. 用 Playwright 打开 `https://www.lingguang.com`，保持窗口可见
2. 告诉用户：**请在弹出的浏览器窗口里扫码登录，登完跟我说一声**
3. 用户确认后，从浏览器上下文取 cookie：

```python
cookies = context.cookies([
    "https://www.lingguang.com",
    "https://cognihome.lingguang.com",
])
```

只保留这三个：`ctoken`、`prod_LINGGUANGJSESSIONID`、`spanner`，
拼成 `name=value; name=value` 的形式。

4. 写进临时文件，导入并验证：

```bash
lingguang auth import /tmp/lg-cookie.txt
lingguang auth status
```

5. **立即删掉那个临时文件**，不要把 cookie 留在磁盘上

## 为什么不能用 document.cookie

`prod_LINGGUANGJSESSIONID` 是 **HttpOnly** 的，页面里的 JS 读不到。

## 三个 cookie 谁必需

实测结果：

| cookie | 必需 | 说明 |
|---|---|---|
| `prod_LINGGUANGJSESSIONID` | **是** | 缺了接口直接报错 |
| `ctoken` | **是** | 请求路径里要带 |
| `spanner` | 否 | 实测不是必须，但带着更稳 |

只带 `ctoken` 会失败，别为了省事只复制一个。

## 方式二：教用户手动复制

没有 Playwright，或者用户选了自己来，就一步步引导，
**不要只说"去弄个 cookie"**：

> 1. 浏览器打开 https://www.lingguang.com 并登录
> 2. 按 `F12`，切到 **Application** 标签（中文版叫「应用」）
> 3. 左边找 **Storage → Cookies → https://www.lingguang.com**
> 4. 右边表格里找这三个，双击 Value 列复制：
>    - `ctoken`
>    - `prod_LINGGUANGJSESSIONID`
>    - `spanner`
> 5. `spanner` 的域名是 `cognihome.lingguang.com`，如果上面找不到，
>    点左边那一项再找
> 6. 拼成一行发给我，分号加空格隔开，像这样：
>    `ctoken=xxx; prod_LINGGUANGJSESSIONID=yyy; spanner=zzz`

用户发来后，帮他导入：

```bash
lingguang auth import <他给的文件或内容>
lingguang auth status
```

**提醒用户**：控制台敲 `document.cookie` 拿不到 JSESSIONID，必须在面板里复制。

## 导入失败排查

| 现象 | 原因 |
|---|---|
| 提示找不到 ctoken | 复制漏了，或者复制成了别的东西 |
| 验证未通过，接口返回失败 | 多半缺 `prod_LINGGUANGJSESSIONID` |
| 提示缺少关键 cookie | 有值没带全，让用户补 |
| 导入成功但很快又失效 | 用户在别处重新登录，旧会话被顶掉 |
