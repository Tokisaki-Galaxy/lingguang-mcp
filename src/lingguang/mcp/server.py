"""MCP stdio server。

关键约束：stdout 只能写合法 MCP 消息。
任何第三方库顺手 print 都会破坏协议帧，所以启动时立刻把 stdout 重定向到 stderr，
最后再把真实句柄交还给传输层。

规范版本 2026-07-28。本地单客户端场景用 stdio，不用 Streamable HTTP：
后者强制 Origin 校验、鉴权、绑本地回环，对单机使用是纯负担。
"""

from __future__ import annotations

import io
import sys
from typing import Any

# 必须在任何业务 import 之前完成重定向
_REAL_STDOUT = sys.stdout
sys.stdout = sys.stderr

import asyncio  # noqa: E402
import json  # noqa: E402

from ..core.errors import LingguangError  # noqa: E402
from ..core.service import Service  # noqa: E402
from .tools import TOOL_DEFINITIONS, dispatch  # noqa: E402

PROTOCOL_VERSION = "2026-07-28"


def _write(message: dict[str, Any]) -> None:
    payload = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
    _REAL_STDOUT.write(payload + "\n")
    _REAL_STDOUT.flush()


def _response(req_id: Any, result: dict[str, Any]) -> None:
    _write({"jsonrpc": "2.0", "id": req_id, "result": result})


def _error(req_id: Any, code: int, message: str) -> None:
    _write({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}})


def _handle_initialize(req_id: Any, params: dict[str, Any]) -> None:
    _response(
        req_id,
        {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "lingguang-mcp", "version": "0.1.0"},
        },
    )


def _handle_tools_list(req_id: Any) -> None:
    _response(req_id, {"tools": TOOL_DEFINITIONS})


def _handle_tools_call(req_id: Any, params: dict[str, Any], service: Service) -> None:
    name = str(params.get("name") or "")
    args = params.get("arguments") or {}
    if not isinstance(args, dict):
        _error(req_id, -32602, "arguments 必须是对象")
        return
    try:
        result = dispatch(name, args, service)
    except LingguangError as exc:
        _response(
            req_id,
            {
                "content": [{"type": "text", "text": f"执行失败: {exc}"}],
                "isError": True,
            },
        )
        return
    except KeyError as exc:
        _response(
            req_id,
            {
                "content": [{"type": "text", "text": f"缺少参数: {exc}"}],
                "isError": True,
            },
        )
        return
    except Exception as exc:  # noqa: BLE001
        _response(
            req_id,
            {
                "content": [{"type": "text", "text": f"未预期的错误: {exc}"}],
                "isError": True,
            },
        )
        return

    _response(
        req_id,
        {
            "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}],
            "structuredContent": result,
            "isError": False,
        },
    )


async def _serve() -> None:
    service = Service()

    while True:
        line = sys.stdin.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            _error(None, -32700, "JSON 解析失败")
            continue
        if not isinstance(message, dict):
            _error(None, -32600, "请求必须是对象")
            continue

        method = message.get("method")
        req_id = message.get("id")
        params = message.get("params") or {}
        if not isinstance(params, dict):
            params = {}

        if method == "initialize":
            _handle_initialize(req_id, params)
        elif method == "notifications/initialized":
            continue  # 通知不需要响应
        elif method == "tools/list":
            _handle_tools_list(req_id)
        elif method == "tools/call":
            _handle_tools_call(req_id, params, service)
        elif method == "ping":
            _response(req_id, {})
        elif req_id is not None:
            _error(req_id, -32601, f"未知方法: {method}")


def run() -> None:
    try:
        asyncio.run(_serve())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()
