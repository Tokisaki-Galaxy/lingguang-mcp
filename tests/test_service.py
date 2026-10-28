"""Service 层测试。

重点覆盖几个容易出事的逻辑：
  - ask 断流后返回 dispatched_unknown 而不是抛异常
  - get_answer 的四种状态判定
  - delete 必须有 confirm
  - sink 的幂等调用
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from lingguang.core.errors import ContractError
from lingguang.core.models import Turn
from lingguang.core.service import Service
from lingguang.core.sink import NullSink


class FakeClient:
    """可控的假客户端，不触网。"""

    def __init__(self) -> None:
        self.ctoken = "fake-token"
        self.history: dict[str, list[dict[str, Any]]] = {}
        self.sessions: list[dict[str, Any]] = []
        self.has_more = False
        self.raise_on_stream: Exception | None = None
        self.stream_events: list[dict[str, Any]] = []
        self.deleted: list[tuple[str, str]] = []
        self.scene_map: dict[str, str] = {}
        self.delete_ignores_scene = False

    def list_sessions(self, page_size: int = 30, cursor: int | None = None) -> dict[str, Any]:
        return {"dataList": self.sessions, "hasMore": self.has_more}

    def get_history(self, session_id: str, page_size: int = 30) -> dict[str, Any]:
        return {"dataList": self.history.get(session_id, [])}

    def delete_session(self, session_id: str, scene: str = "LEOPARD") -> dict[str, Any]:
        """模拟真实行为：sceneCode 不匹配时静默不删。"""
        self.deleted.append((session_id, scene))
        expected = self.scene_map.get(session_id)
        if not self.delete_ignores_scene and expected and expected != scene:
            return {"success": True}
        self.scene_map.pop(session_id, None)
        self.sessions = [s for s in self.sessions if s.get("sessionId") != session_id]
        return {"success": True}

    def find_session_scene(self, session_id: str) -> str | None:
        return self.scene_map.get(session_id)

    def session_exists(self, session_id: str) -> bool:
        return session_id in self.scene_map

    def login_check(self) -> dict[str, Any]:
        return {"success": True}

    def stream_chat(self, query: str, session_id: str | None = None, query_id: str | None = None, **kw: Any):
        if self.raise_on_stream is not None:
            raise self.raise_on_stream
        for ev in self.stream_events:
            yield ev


def _answer_item(query_id: str, text: str, cot: str = "") -> dict[str, Any]:
    return {
        "itemType": "ANSWER",
        "queryId": query_id,
        "sessionId": "s1",
        "status": "VALID",
        "time": 1700000000001,
        "templateData": {"text": text, "cot": cot},
    }


class TestAsk:
    def test_generates_session_when_absent(self) -> None:
        client = FakeClient()
        client.stream_events = [{"sessionId": "x", "success": True}]
        svc = Service(cookie="ctoken=x", client=client)  # type: ignore[arg-type]
        result = svc.ask("测试问题")
        assert result.session_id
        assert result.query_id
        assert result.status == "submitted"

    def test_empty_stream_still_accepted(self) -> None:
        """流为空不代表失败。服务端受理了但没推事件时，结果仍要靠 get_answer 取。"""
        client = FakeClient()
        svc = Service(cookie="ctoken=x", client=client)  # type: ignore[arg-type]
        result = svc.ask("测试问题")
        assert result.status == "accepted"

    def test_uses_given_session(self) -> None:
        client = FakeClient()
        svc = Service(cookie="ctoken=x", client=client)  # type: ignore[arg-type]
        result = svc.ask("测试", session_id="fixed-session")
        assert result.session_id == "fixed-session"

    def test_stream_break_returns_dispatched_unknown(self) -> None:
        """断流不能抛异常。提问可能已经到达服务端，要交给 get_answer 确认。"""
        client = FakeClient()
        client.raise_on_stream = ConnectionError("连接重置")
        svc = Service(cookie="ctoken=x", client=client)  # type: ignore[arg-type]
        result = svc.ask("测试")
        assert result.status == "dispatched_unknown"
        assert result.query_id

    def test_empty_query_rejected(self) -> None:
        client = FakeClient()
        svc = Service(cookie="ctoken=x", client=client)  # type: ignore[arg-type]
        with pytest.raises(ContractError):
            svc.ask("   ")


class TestGetAnswer:
    def test_returns_done_when_present(self) -> None:
        client = FakeClient()
        client.history["s1"] = [
            {"itemType": "QUERY", "queryId": "q1", "query": "问题"},
            _answer_item("q1", "这是回答"),
        ]
        svc = Service(cookie="ctoken=x", client=client)  # type: ignore[arg-type]
        out = svc.get_answer("q1", session_id="s1", wait_seconds=0)
        assert out["status"] == "done"
        assert out["text"] == "这是回答"

    def test_pending_when_absent(self) -> None:
        client = FakeClient()
        svc = Service(cookie="ctoken=x", client=client)  # type: ignore[arg-type]
        out = svc.get_answer("q-missing", session_id="s1", wait_seconds=0)
        assert out["status"] == "pending"

    def test_awaiting_confirmation_when_turn_has_no_text(self) -> None:
        """该轮存在但无正文，可能是等待人工确认（APASS 这类机制）。"""
        client = FakeClient()
        client.history["s1"] = [
            {"itemType": "QUERY", "queryId": "q2", "query": "高危操作"},
            _answer_item("q2", ""),
        ]
        svc = Service(cookie="ctoken=x", client=client)  # type: ignore[arg-type]
        out = svc.get_answer("q2", session_id="s1", wait_seconds=0)
        assert out["status"] == "awaiting_confirmation"
        assert any("人工确认" in w for w in out["warnings"])

    def test_polls_until_appears(self) -> None:
        client = FakeClient()
        svc = Service(cookie="ctoken=x", client=client)  # type: ignore[arg-type]
        calls = {"n": 0}

        def fake_sleep(_: float) -> None:
            calls["n"] += 1
            if calls["n"] >= 2:
                client.history["s1"] = [
                    {"itemType": "QUERY", "queryId": "q3", "query": "问题"},
                    _answer_item("q3", "迟到的回答"),
                ]

        out = svc.get_answer("q3", session_id="s1", wait_seconds=30, sleep=fake_sleep)
        assert out["status"] == "done"
        assert out["text"] == "迟到的回答"

    def test_recovers_from_pending_journal(self) -> None:
        """session_id 不知道时，靠 pending journal 找回。"""
        client = FakeClient()
        svc = Service(cookie="ctoken=x", client=client)  # type: ignore[arg-type]
        result = svc.ask("会被断流的问题", session_id="recover-session")
        client.history["recover-session"] = [
            {"itemType": "QUERY", "queryId": result.query_id, "query": "会被断流的问题"},
            _answer_item(result.query_id, "恢复出来的答案"),
        ]
        out = svc.get_answer(result.query_id, session_id=None, wait_seconds=0)
        assert out["status"] == "done"
        assert out["text"] == "恢复出来的答案"


class TestTranscript:
    def test_returns_turns(self) -> None:
        client = FakeClient()
        client.history["s1"] = [
            {"itemType": "QUERY", "queryId": "q1", "query": "问题一"},
            _answer_item("q1", "回答一"),
        ]
        svc = Service(cookie="ctoken=x", client=client)  # type: ignore[arg-type]
        out = svc.get_transcript("s1")
        assert out["count"] == 1
        assert out["turns"][0]["answer"] == "回答一"

    def test_keyword_filters(self) -> None:
        client = FakeClient()
        client.history["s1"] = [
            {"itemType": "QUERY", "queryId": "q1", "query": "账单"},
            _answer_item("q1", "账单回答"),
            {"itemType": "QUERY", "queryId": "q2", "query": "天气"},
            _answer_item("q2", "天气回答"),
        ]
        svc = Service(cookie="ctoken=x", client=client)  # type: ignore[arg-type]
        out = svc.get_transcript("s1", keyword="账单")
        assert out["count"] == 1

    def test_empty_session_id_rejected(self) -> None:
        client = FakeClient()
        svc = Service(cookie="ctoken=x", client=client)  # type: ignore[arg-type]
        with pytest.raises(ContractError):
            svc.get_transcript("")


class TestDelete:
    def test_requires_confirm(self) -> None:
        client = FakeClient()
        svc = Service(cookie="ctoken=x", client=client)  # type: ignore[arg-type]
        with pytest.raises(ContractError):
            svc.delete_session("s1", confirm=False)
        assert client.deleted == []

    def test_deletes_with_correct_scene(self) -> None:
        client = FakeClient()
        client.scene_map["s1"] = "WEB"
        svc = Service(cookie="ctoken=x", client=client)  # type: ignore[arg-type]
        out = svc.delete_session("s1", confirm=True)
        assert out["deleted"] is True
        # 必须用会话自身的场景，不能硬编码
        assert client.deleted == [("s1", "WEB")]
        assert not client.session_exists("s1")

    def test_leopard_session_uses_leopard(self) -> None:
        client = FakeClient()
        client.scene_map["s1"] = "LEOPARD"
        svc = Service(cookie="ctoken=x", client=client)  # type: ignore[arg-type]
        svc.delete_session("s1", confirm=True)
        assert client.deleted == [("s1", "LEOPARD")]

    def test_missing_session_is_idempotent(self) -> None:
        client = FakeClient()
        svc = Service(cookie="ctoken=x", client=client)  # type: ignore[arg-type]
        out = svc.delete_session("ghost", confirm=True)
        assert out["deleted"] is True
        assert "本来就不存在" in out.get("note", "")

    def test_detects_silent_delete_failure(self) -> None:
        """场景不匹配时上游返回成功但不删，我们必须发现并报错。"""

        class StubbornClient(FakeClient):
            def delete_session(self, session_id: str, scene: str = "LEOPARD") -> dict[str, Any]:
                self.deleted.append((session_id, scene))
                return {"success": True}  # 静默什么都不删

        client = StubbornClient()
        client.scene_map["s1"] = "WEB"
        svc = Service(cookie="ctoken=x", client=client)  # type: ignore[arg-type]
        with pytest.raises(ContractError, match="删除未生效"):
            svc.delete_session("s1", confirm=True)


class RecordingSink:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def upsert_turn(self, session_id: str, turn: Turn, source: str) -> None:
        self.calls.append((session_id, turn.query_id, source))


class TestSink:
    def test_transcript_writes_to_sink(self) -> None:
        client = FakeClient()
        client.history["s1"] = [
            {"itemType": "QUERY", "queryId": "q1", "query": "问题"},
            _answer_item("q1", "回答"),
        ]
        sink = RecordingSink()
        svc = Service(cookie="ctoken=x", client=client, sink=sink)  # type: ignore[arg-type]
        svc.get_transcript("s1")
        assert sink.calls == [("s1", "q1", "transcript")]

    def test_default_sink_is_null(self) -> None:
        client = FakeClient()
        svc = Service(cookie="ctoken=x", client=client)  # type: ignore[arg-type]
        assert isinstance(svc.sink, NullSink)
