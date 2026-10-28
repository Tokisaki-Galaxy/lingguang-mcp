"""MCP 协议层测试。

用 subprocess 驱动真实的 stdio server，验证协议帧正确、
stdout 没有被污染、schema 合法。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def _run_server(messages: list[dict]) -> list[dict]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    payload = "\n".join(json.dumps(m) for m in messages) + "\n"
    proc = subprocess.run(
        [sys.executable, "-m", "lingguang.mcp.server"],
        input=payload,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=60,
    )
    out = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        out.append(json.loads(line))
    return out


def test_initialize_responds() -> None:
    responses = _run_server(
        [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}]
    )
    assert len(responses) == 1
    assert responses[0]["id"] == 1
    result = responses[0]["result"]
    assert result["protocolVersion"]
    assert result["serverInfo"]["name"] == "lingguang-mcp"
    assert "tools" in result["capabilities"]


def test_stdout_only_contains_protocol_frames() -> None:
    """stdout 必须只出现合法 JSON-RPC 消息。

    这是 stdio 传输的硬约束，任何 print 都会破坏协议。
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}) + "\n"
    proc = subprocess.run(
        [sys.executable, "-m", "lingguang.mcp.server"],
        input=payload,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=60,
    )
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)  # 不是 JSON 就会抛异常
        assert obj.get("jsonrpc") == "2.0"


def test_tools_list_returns_six_tools() -> None:
    responses = _run_server(
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        ]
    )
    tools = responses[1]["result"]["tools"]
    names = {t["name"] for t in tools}
    assert names == {
        "list_sessions",
        "get_transcript",
        "ask",
        "get_answer",
        "auth_status",
        "delete_session",
    }


def test_every_tool_has_valid_schema() -> None:
    responses = _run_server(
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        ]
    )
    for tool in responses[1]["result"]["tools"]:
        schema = tool["inputSchema"]
        assert isinstance(schema, dict), f"{tool['name']} inputSchema 必须是对象"
        assert schema.get("type") == "object"
        # 无参数工具按规范用 {"type":"object","additionalProperties":false}
        if "properties" not in schema:
            assert schema.get("additionalProperties") is False, (
                f"{tool['name']} 无 properties 时必须限制 additionalProperties"
            )
        assert tool.get("description"), f"{tool['name']} 缺少描述"


def test_delete_session_is_marked_destructive() -> None:
    responses = _run_server(
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        ]
    )
    tools = {t["name"]: t for t in responses[1]["result"]["tools"]}
    delete = tools["delete_session"]
    assert delete["annotations"]["destructiveHint"] is True
    assert "confirm" in delete["inputSchema"]["properties"]
    assert "confirm" in delete["inputSchema"]["required"]


def test_unknown_method_returns_error() -> None:
    responses = _run_server(
        [{"jsonrpc": "2.0", "id": 9, "method": "nonexistent/method", "params": {}}]
    )
    assert responses[0]["error"]["code"] == -32601


def test_ping_responds() -> None:
    responses = _run_server([{"jsonrpc": "2.0", "id": 5, "method": "ping", "params": {}}])
    assert responses[0]["id"] == 5
    assert responses[0]["result"] == {}


def test_notification_gets_no_response() -> None:
    responses = _run_server(
        [{"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}]
    )
    assert responses == []
