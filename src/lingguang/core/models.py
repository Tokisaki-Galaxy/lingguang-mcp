"""数据模型。

设计原则：全部扁平，不做深层嵌套。
MCP 客户端对嵌套结构处理不一，扁平的模型让模型更容易读懂。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Scene(str, Enum):
    """会话来源场景。

    实测：App 发起的会话是 LEOPARD，网页发起的是 WEB。
    这个字段不做数据隔离，查询时传任一值都返回同一份列表，
    但保留原值用于追溯来源。
    """

    LEOPARD = "LEOPARD"
    WEB = "WEB"


class AnswerStatus(str, Enum):
    """get_answer 的返回状态，三态。

    pending: 该轮还没出现在历史里，任务可能仍在跑
    dispatched_unknown: SSE 断流，提问已发出但结果未知
    awaiting_confirmation: 该轮出现了但没有正文，可能等待人工确认
                            （对应 APASS 高危确认这类未落地的机制）
    done: 拿到完整结果
    """

    PENDING = "pending"
    DISPATCHED_UNKNOWN = "dispatched_unknown"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    DONE = "done"


@dataclass
class Session:
    id: str
    summary: str
    scene: Scene
    created_at: int
    updated_at: int
    status: str = "VALID"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "summary": self.summary,
            "scene": self.scene.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "status": self.status,
        }


@dataclass
class ToolCall:
    """一次工具调用。

    实测结构里只有 itemId、groupId、display.title 三个字段，
    没有风险等级或确认标记。将来上游加了确认类事件，
    会被 parser 的未知事件宽容逻辑记进 warnings，不会静默丢弃。
    """

    title: str
    item_id: str = ""
    group_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"title": self.title, "item_id": self.item_id, "group_id": self.group_id}


@dataclass
class Turn:
    """一轮问答。

    query_id 是稳定标识，用作 sink 的去重依据。
    """

    session_id: str
    query_id: str
    query: str = ""
    answer: str = ""
    tools: list[ToolCall] = field(default_factory=list)
    agent_deltas: list[str] = field(default_factory=list)
    summary: str = ""
    status: str = "VALID"
    created_at: int = 0
    raw_text: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def tool_titles(self) -> list[str]:
        return [t.title for t in self.tools]

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "query_id": self.query_id,
            "query": self.query,
            "answer": self.answer,
            "tools": self.tool_titles,
            "summary": self.summary,
            "status": self.status,
            "created_at": self.created_at,
            "warnings": self.warnings,
        }

    def to_raw_dict(self) -> dict[str, Any]:
        """含原始 HTML 的完整形态，用于 export --format raw 兜底。"""
        d = self.to_dict()
        d["raw_text"] = self.raw_text
        d["agent_deltas"] = self.agent_deltas
        return d


@dataclass
class AskResult:
    session_id: str
    query_id: str
    status: str = "submitted"

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "query_id": self.query_id,
            "status": self.status,
        }
