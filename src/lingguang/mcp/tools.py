"""MCP tools 定义。

按 MCP 规范 2026-07-28：
  - inputSchema 必须是合法 JSON Schema
  - 提供 outputSchema 时，structuredContent 必须符合它
  - 同时返回 TextContent 文本块做兼容
  - annotations 默认不可信，不依赖它做安全判断

6 个工具，能力与 CLI 对齐。
"""

from __future__ import annotations

import json
from typing import Any

from ..core.errors import LingguangError
from ..core.service import Service

_MAX_LIMIT = 30


def _text(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """MCP 内容块。结构化数据同时给一份文本，兼容旧客户端。"""
    return [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}]


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "list_sessions",
        "title": "列出灵光会话",
        "description": (
            "列出当前账号下的灵光会话，最近的在前。"
            "返回 next_cursor，为 null 表示没有更多。"
            "注意游标是 best-effort，不保证无遗漏，需要严格全量时用 export。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": _MAX_LIMIT,
                    "default": _MAX_LIMIT,
                    "description": "每页条数，上限 30",
                },
                "cursor": {
                    "type": ["integer", "null"],
                    "description": "上一页返回的 next_cursor，首页传 null",
                },
            },
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "sessions": {"type": "array", "items": {"type": "object"}},
                "next_cursor": {"type": ["integer", "null"]},
            },
            "required": ["sessions", "next_cursor"],
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": True},
    },
    {
        "name": "get_transcript",
        "title": "读取会话内容",
        "description": (
            "读取一个会话的完整问答记录，包含每轮的正文和 Agent 的工具执行轨迹。"
            "工具轨迹是本工具的核心价值：它记录了 Agent 每一步真实调用了什么子程序。"
            "keyword 用于在正文和工具标题里做内存过滤。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "minLength": 1, "description": "会话 id"},
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": _MAX_LIMIT,
                    "default": _MAX_LIMIT,
                    "description": "最多返回多少条原始记录",
                },
                "keyword": {"type": ["string", "null"], "description": "关键词过滤"},
            },
            "required": ["session_id"],
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "turns": {"type": "array", "items": {"type": "object"}},
                "count": {"type": "integer"},
            },
            "required": ["turns", "count"],
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": True},
    },
    {
        "name": "ask",
        "title": "向灵光提问",
        "description": (
            "提交一个问题给灵光，立即返回，不等待结果。"
            "必须配合 get_answer 取回结果。账单类问题通常要跑 20 到 30 秒。"
            "session_id 不传时自动新建会话，返回里会带上新会话 id。"
            "如果返回 status 为 dispatched_unknown，说明提问已发出但连接中断，"
            "请用 get_answer 确认结果，不要重复提问，否则会重复触发账单查询。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 1, "description": "要问的问题"},
                "session_id": {
                    "type": ["string", "null"],
                    "description": "目标会话 id，不传则新建",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "query_id": {"type": "string"},
                "status": {"type": "string"},
            },
            "required": ["session_id", "query_id", "status"],
        },
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "openWorldHint": True,
        },
    },
    {
        "name": "get_answer",
        "title": "取回提问结果",
        "description": (
            "按 query_id 取回 ask 的结果。"
            "wait_seconds 为 0 时只查一次，大于 0 时轮询等待，上限 60 秒。"
            "返回 status 有四种：pending 表示还没出现，"
            "dispatched_unknown 表示提问已发出但结果未知，"
            "awaiting_confirmation 表示该轮已存在但无正文，可能需要用户在灵光 App 内手动确认，"
            "done 表示拿到完整结果。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query_id": {"type": "string", "minLength": 1, "description": "ask 返回的 query_id"},
                "session_id": {"type": ["string", "null"], "description": "会话 id，可选"},
                "wait_seconds": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 60,
                    "default": 0,
                    "description": "等待秒数，上限 60",
                },
            },
            "required": ["query_id"],
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "session_id": {"type": "string"},
                "query_id": {"type": "string"},
                "text": {"type": "string"},
                "tools": {"type": "array", "items": {"type": "string"}},
                "warnings": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["status", "query_id", "text", "tools", "warnings"],
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": True},
    },
    {
        "name": "auth_status",
        "title": "检查登录态",
        "description": (
            "检查灵光登录凭据是否有效。"
            "cookie 失效时工具完全不可用，用这个工具确认状态，"
            "失效时提示用户重新导入。"
        ),
        "inputSchema": {"type": "object", "additionalProperties": False},
        "outputSchema": {
            "type": "object",
            "properties": {
                "valid": {"type": "boolean"},
                "imported": {"type": "boolean"},
                "hint": {"type": "string"},
            },
            "required": ["valid"],
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": True},
    },
    {
        "name": "delete_session",
        "title": "删除会话",
        "description": (
            "删除一个灵光会话。删除后不可恢复。"
            "调用前必须先用 get_transcript 确认目标会话是哪一个。"
            "必须显式传 confirm=true，否则直接拒绝。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "minLength": 1, "description": "要删除的会话 id"},
                "confirm": {
                    "type": "boolean",
                    "description": "必须为 true，表示确认这是破坏性操作",
                },
            },
            "required": ["session_id", "confirm"],
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "deleted": {"type": "boolean"},
                "session_id": {"type": "string"},
            },
            "required": ["deleted", "session_id"],
        },
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    },
]


def dispatch(name: str, args: dict[str, Any], service: Service) -> dict[str, Any]:
    """执行工具。返回 structuredContent 形态的字典。"""
    if name == "list_sessions":
        return service.list_sessions(
            limit=int(args.get("limit") or _MAX_LIMIT),
            cursor=args.get("cursor"),
        )
    if name == "get_transcript":
        return service.get_transcript(
            session_id=str(args["session_id"]),
            limit=int(args.get("limit") or _MAX_LIMIT),
            keyword=args.get("keyword"),
        )
    if name == "ask":
        result = service.ask(
            query=str(args["query"]),
            session_id=args.get("session_id"),
        )
        return result.to_dict()
    if name == "get_answer":
        return service.get_answer(
            query_id=str(args["query_id"]),
            session_id=args.get("session_id"),
            wait_seconds=int(args.get("wait_seconds") or 0),
        )
    if name == "auth_status":
        return service.auth_status()
    if name == "delete_session":
        return service.delete_session(
            session_id=str(args["session_id"]),
            confirm=bool(args.get("confirm")),
        )
    raise LingguangError(f"未知工具: {name}")
