"""CLI 入口。core 的薄壳，不含业务判断。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer

from ..core.auth import (
    Credentials,
    clear_credentials,
    describe_status,
    get_cookie,
    parse_cookie_string,
    save_credentials,
)
from ..core.errors import LingguangError
from ..core.service import Service

app = typer.Typer(
    name="lingguang",
    help="灵光 AI 的 MCP 与 CLI 工具",
    no_args_is_help=True,
    add_completion=False,
)

auth_app = typer.Typer(help="管理登录凭据", no_args_is_help=True)
sessions_app = typer.Typer(help="查看与管理会话", no_args_is_help=True)
app.add_typer(auth_app, name="auth")
app.add_typer(sessions_app, name="sessions")


def _fail(message: str, code: int = 1) -> None:
    """错误统一走 stderr，stdout 只留数据。"""
    typer.echo(f"错误: {message}", err=True)
    raise typer.Exit(code)


def _service() -> Service:
    try:
        return Service()
    except LingguangError as exc:
        _fail(str(exc))


def _dump(data: object) -> None:
    typer.echo(json.dumps(data, ensure_ascii=False, indent=2))


# ---------------- auth ----------------


@auth_app.command("status")
def auth_status() -> None:
    """检查登录态。"""
    status = describe_status()
    if status.get("imported"):
        try:
            svc = Service()
            status = svc.auth_status()
        except LingguangError as exc:
            status["probe"] = f"无法探测: {exc}"
    _dump(status)


@auth_app.command("import")
def auth_import(
    source: Annotated[Optional[Path], typer.Argument(help="含 cookie 的文件")] = None,
) -> None:
    """导入 cookie。

    支持整段 cookie 字符串，也支持从 curl 命令里粘。
    导入后会立即验证一次，失败就报错，不等下次用才炸。
    """
    raw = source.read_text(encoding="utf-8") if source else typer.get_text_stream("stdin").read()

    try:
        cookie = parse_cookie_string(raw)
    except LingguangError as exc:
        _fail(str(exc))

    creds = Credentials(cookie=cookie, imported_at=__import__("time").time())
    backend = save_credentials(creds)
    where = (
        "Windows 凭据管理器"
        if backend == "windows-credential-manager"
        else "配置文件"
    )
    typer.echo(f"已保存到{where}")

    try:
        svc = Service(cookie=cookie)
        result = svc.auth_status()
    except LingguangError as exc:
        _fail(f"已保存但验证失败: {exc}")

    if result.get("valid"):
        typer.echo("验证通过，cookie 可用")
    else:
        typer.echo(f"警告: 验证未通过 {result.get('probe', '')}", err=True)
    missing = result.get("missing_keys") or []
    if missing:
        typer.echo(f"注意: 缺少关键 cookie {missing}，稳定性可能受影响", err=True)


@auth_app.command("clear")
def auth_clear() -> None:
    """删除本地保存的 cookie。"""
    clear_credentials()
    typer.echo("已清除")


# ---------------- sessions ----------------


@sessions_app.command("list")
def sessions_list(
    limit: Annotated[int, typer.Option("--limit", "-n", help="每页条数，上限 30")] = 30,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON")] = False,
) -> None:
    """列出会话。"""
    svc = _service()
    try:
        data = svc.list_sessions(limit=limit)
    except LingguangError as exc:
        _fail(str(exc))

    if json_output:
        _dump(data)
        return
    sessions = data.get("sessions") or []
    if not sessions:
        typer.echo("没有会话")
        return
    for s in sessions:
        typer.echo(f"{s['id']}  {s['summary']}  [{s['scene']}]")


@sessions_app.command("show")
def sessions_show(
    session_id: Annotated[str, typer.Argument(help="会话 id")],
    keyword: Annotated[Optional[str], typer.Option("--keyword", "-k", help="按关键词过滤")] = None,
    and_tools: Annotated[bool, typer.Option("--tools", help="显示工具轨迹")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON")] = False,
) -> None:
    """查看会话内容。"""
    svc = _service()
    try:
        data = svc.get_transcript(session_id, keyword=keyword)
    except LingguangError as exc:
        _fail(str(exc))

    if json_output:
        _dump(data)
        return

    turns = data.get("turns") or []
    if not turns:
        typer.echo("没有匹配的轮次")
        return
    for i, turn in enumerate(turns, 1):
        typer.echo(f"\n=== 第 {i} 轮 ===")
        if turn["query"]:
            typer.echo(f"问: {turn['query']}")
        if and_tools and turn["tools"]:
            typer.echo(f"工具: {' / '.join(turn['tools'])}")
        if turn["warnings"]:
            typer.echo(f"提示: {'; '.join(turn['warnings'])}")
        typer.echo(turn["answer"] or "(无正文)")


@sessions_app.command("delete")
def sessions_delete(
    session_id: Annotated[str, typer.Argument(help="会话 id")],
    yes: Annotated[bool, typer.Option("--yes", "-y", help="确认删除")] = False,
) -> None:
    """删除会话。不可恢复。"""
    if not yes:
        _fail("删除不可恢复，请加 --yes 确认")
    svc = _service()
    try:
        result = svc.delete_session(session_id, confirm=True)
    except LingguangError as exc:
        _fail(str(exc))
    _dump(result)


# ---------------- ask / answer ----------------


@app.command("ask")
def ask(
    query: Annotated[str, typer.Argument(help="要问灵光的问题")],
    session: Annotated[Optional[str], typer.Option("--session", "-s", help="会话 id，不传则新建")] = None,
    wait: Annotated[bool, typer.Option("--wait", "-w", help="等待结果返回")] = False,
    timeout: Annotated[int, typer.Option("--timeout", help="等待秒数，上限 60")] = 60,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON")] = False,
) -> None:
    """向灵光提问。

    不带 --wait 时立即返回 session_id 和 query_id，
    后续用 answer 命令取结果。
    """
    svc = _service()
    try:
        result = svc.ask(query, session_id=session)
    except LingguangError as exc:
        _fail(str(exc))

    if not wait:
        if json_output:
            _dump(result.to_dict())
        else:
            typer.echo(f"session: {result.session_id}")
            typer.echo(f"query:   {result.query_id}")
            if result.status == "dispatched_unknown":
                typer.echo("状态: 已发出但结果未知，请用 answer 命令确认，不要重复提问", err=True)
        return

    answer = svc.get_answer(result.query_id, session_id=result.session_id, wait_seconds=timeout)
    if json_output:
        _dump(answer)
        return
    if answer["status"] == "done":
        typer.echo(answer["text"])
        if answer["tools"]:
            typer.echo(f"\n工具轨迹: {' / '.join(answer['tools'])}", err=True)
    else:
        typer.echo(f"状态: {answer['status']}", err=True)
        for w in answer.get("warnings") or []:
            typer.echo(f"提示: {w}", err=True)


@app.command("answer")
def answer(
    query_id: Annotated[str, typer.Argument(help="ask 返回的 query id")],
    session: Annotated[Optional[str], typer.Option("--session", "-s", help="会话 id")] = None,
    wait: Annotated[int, typer.Option("--wait", "-w", help="等待秒数，上限 60")] = 0,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON")] = False,
) -> None:
    """取回提问结果。"""
    svc = _service()
    try:
        data = svc.get_answer(query_id, session_id=session, wait_seconds=wait)
    except LingguangError as exc:
        _fail(str(exc))

    if json_output:
        _dump(data)
        return
    if data["status"] == "done":
        typer.echo(data["text"])
    else:
        typer.echo(f"状态: {data['status']}")
        if data["status"] == "awaiting_confirmation":
            typer.echo("这次提问可能需要你在灵光 App 里手动确认", err=True)


# ---------------- export ----------------


@app.command("export")
def export(
    session_id: Annotated[str, typer.Argument(help="会话 id")],
    fmt: Annotated[str, typer.Option("--format", "-f", help="md / json / jsonl / raw")] = "md",
    output: Annotated[Optional[Path], typer.Option("--output", "-o", help="输出文件")] = None,
) -> None:
    """导出会话。

    raw 格式输出未解析的原始 JSON，解析器失效时用它兜底。
    """
    svc = _service()

    if fmt == "raw":
        try:
            raw = svc.get_raw_history(session_id)
        except LingguangError as exc:
            _fail(str(exc))
        text = json.dumps(raw, ensure_ascii=False, indent=2)
    else:
        try:
            data = svc.get_transcript(session_id)
        except LingguangError as exc:
            _fail(str(exc))
        turns = data.get("turns") or []
        if fmt == "json":
            text = json.dumps(turns, ensure_ascii=False, indent=2)
        elif fmt == "jsonl":
            text = "\n".join(json.dumps(t, ensure_ascii=False) for t in turns)
        else:
            lines: list[str] = []
            for i, turn in enumerate(turns, 1):
                lines.append(f"## 第 {i} 轮\n")
                if turn["query"]:
                    lines.append(f"**问**: {turn['query']}\n")
                if turn["tools"]:
                    lines.append(f"**工具**: {' / '.join(turn['tools'])}\n")
                lines.append(f"{turn['answer']}\n")
            text = "\n".join(lines)

    if output:
        output.write_text(text, encoding="utf-8")
        typer.echo(f"已写入 {output}")
    else:
        typer.echo(text)


# ---------------- 运维 ----------------


@app.command("doctor")
def doctor() -> None:
    """环境自检。"""
    ok = True

    # cookie
    status = describe_status()
    if not status.get("imported"):
        typer.echo("[失败] 未导入 cookie", err=True)
        ok = False
    else:
        missing = status.get("missing_keys") or []
        if missing:
            typer.echo(f"[警告] 缺少关键 cookie: {missing}")
        else:
            typer.echo("[通过] cookie 齐全")

    if not ok:
        raise typer.Exit(1)

    # 连通性
    try:
        svc = Service()
        probe = svc.auth_status()
        if probe.get("valid"):
            typer.echo("[通过] loginCheck 成功")
        else:
            typer.echo(f"[失败] {probe.get('probe', 'loginCheck 未通过')}", err=True)
            ok = False
    except LingguangError as exc:
        typer.echo(f"[失败] 无法连接: {exc}", err=True)
        ok = False

    # 解析器自检
    try:
        from ..core.parser import parse_artifact_text
        from pathlib import Path as _Path

        fixture = _Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "answer_billing.raw.html"
        if fixture.exists():
            text = parse_artifact_text(fixture.read_text(encoding="utf-8"))
            if text:
                typer.echo(f"[通过] 解析器能提取正文（{len(text)} 字符）")
            else:
                typer.echo("[失败] 解析器未提取到正文，上游可能改版", err=True)
                ok = False
        else:
            typer.echo("[跳过] 未找到 fixture")
    except Exception as exc:  # noqa: BLE001
        typer.echo(f"[失败] 解析器自检异常: {exc}", err=True)
        ok = False

    raise typer.Exit(0 if ok else 1)


@app.command("serve")
def serve() -> None:
    """启动 MCP stdio server。"""
    from ..mcp.server import run

    run()


def main() -> None:
    app()


if __name__ == "__main__":
    main()
