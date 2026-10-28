"""核心层：解析、传输、业务编排。

cli 与 mcp 只能通过 service、models、errors 访问这里，
不要直接碰 client 和 parser。
"""

from .errors import (
    AuthError,
    ContractError,
    LingguangError,
    RateLimitError,
    TruncatedResponseError,
    TransportError,
)
from .models import AnswerStatus, AskResult, Scene, Session, ToolCall, Turn
from .parser import (
    build_turn,
    collect_unknown_events,
    pair_turns,
    parse_artifact_text,
    parse_cot_agent_deltas,
    parse_cot_tools,
)
from .service import Service
from .sink import MessageSink, NullSink

__all__ = [
    "AuthError",
    "ContractError",
    "LingguangError",
    "RateLimitError",
    "TruncatedResponseError",
    "TransportError",
    "AnswerStatus",
    "AskResult",
    "Scene",
    "Session",
    "ToolCall",
    "Turn",
    "build_turn",
    "collect_unknown_events",
    "pair_turns",
    "parse_artifact_text",
    "parse_cot_agent_deltas",
    "parse_cot_tools",
    "Service",
    "MessageSink",
    "NullSink",
]
