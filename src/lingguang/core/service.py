"""业务编排。MCP 与 CLI 都只通过这一层访问能力。

这里集中了几个关键机制：
  1. ask 的可恢复性：提交前写 pending journal，断流返回 dispatched_unknown
  2. get_answer 的四种状态判定，包括 APASS 确认这类未落地机制
  3. 轮询退避，按人级低频设计，避免把账号打进风控
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .auth import PENDING_FILE, get_cookie, mark_error, mark_ok
from .client import HttpClient
from .errors import AuthError, ContractError, LingguangError
from .models import AnswerStatus, AskResult, Scene, Session, Turn
from .parser import pair_turns
from .sink import MessageSink, NullSink

# 轮询退避：首次 3 秒，之后逐步拉长到 8 秒。
# 高频轮询会被蚂蚁风控标记，连带影响用户在 App 里的正常使用。
_POLL_DELAYS = (3, 5, 8, 8, 8, 8, 8, 8, 8, 8)
MAX_WAIT_SECONDS = 60


@dataclass
class PendingEntry:
    session_id: str
    query_id: str
    query: str
    submitted_at: float


def _append_pending(entry: PendingEntry) -> None:
    PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    with PENDING_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry.__dict__, ensure_ascii=False) + "\n")


def _read_pending() -> list[PendingEntry]:
    if not PENDING_FILE.exists():
        return []
    out: list[PendingEntry] = []
    for line in PENDING_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        out.append(
            PendingEntry(
                session_id=str(data.get("session_id") or ""),
                query_id=str(data.get("query_id") or ""),
                query=str(data.get("query") or ""),
                submitted_at=float(data.get("submitted_at") or 0),
            )
        )
    return out


def _remove_pending(query_id: str) -> None:
    entries = _read_pending()
    kept = [e for e in entries if e.query_id != query_id]
    if len(kept) == len(entries):
        return
    PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    with PENDING_FILE.open("w", encoding="utf-8") as fh:
        for e in kept:
            fh.write(json.dumps(e.__dict__, ensure_ascii=False) + "\n")


class Service:
    def __init__(
        self,
        cookie: str | None = None,
        sink: MessageSink | None = None,
        client: HttpClient | None = None,
    ) -> None:
        self._client = client
        self._cookie = cookie
        self.sink: MessageSink = sink or NullSink()

    @property
    def client(self) -> HttpClient:
        if self._client is None:
            self._client = HttpClient(self._cookie or get_cookie())
        return self._client

    # ---------- 会话 ----------

    def list_sessions(self, limit: int = 30, cursor: int | None = None) -> dict[str, Any]:
        data = self.client.list_sessions(page_size=limit, cursor=cursor)
        raw = data.get("dataList") or []
        sessions: list[Session] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            scene_value = str(item.get("sceneCode") or Scene.LEOPARD.value)
            try:
                scene = Scene(scene_value)
            except ValueError:
                scene = Scene.LEOPARD
            sessions.append(
                Session(
                    id=str(item.get("sessionId") or ""),
                    summary=str(item.get("summary") or ""),
                    scene=scene,
                    created_at=int(item.get("createTime") or 0),
                    updated_at=int(item.get("updateTime") or 0),
                    status=str(item.get("status") or ""),
                )
            )
        next_cursor = None
        if data.get("hasMore") and sessions:
            # latestTime 按 createTime 游标向后翻
            next_cursor = sessions[-1].created_at
        return {
            "sessions": [s.to_dict() for s in sessions],
            "next_cursor": next_cursor,
        }

    def get_transcript(
        self, session_id: str, limit: int = 30, keyword: str | None = None
    ) -> dict[str, Any]:
        if not session_id:
            raise ContractError("session_id 不能为空")
        data = self.client.get_history(session_id, page_size=limit)
        raw = data.get("dataList") or []
        turns = pair_turns(raw)
        for turn in turns:
            self.sink.upsert_turn(session_id, turn, "transcript")

        if keyword:
            lowered = keyword.lower()
            turns = [
                t
                for t in turns
                if lowered in t.query.lower()
                or lowered in t.answer.lower()
                or any(lowered in title.lower() for title in t.tool_titles)
            ]
        return {
            "turns": [t.to_dict() for t in turns],
            "count": len(turns),
        }

    def get_raw_history(self, session_id: str, limit: int = 30) -> list[dict[str, Any]]:
        """原始条目，用于 export --format raw 兜底。

        解析器全挂了也走得通，这是唯一入口场景下最重要的退路。
        """
        data = self.client.get_history(session_id, page_size=limit)
        return [item for item in (data.get("dataList") or []) if isinstance(item, dict)]

    def delete_session(self, session_id: str, confirm: bool = False) -> dict[str, Any]:
        if not confirm:
            raise ContractError(
                "删除是不可恢复的破坏性操作，必须显式传 confirm=True"
            )
        if not session_id:
            raise ContractError("session_id 不能为空")
        self.client.delete_session(session_id)
        _remove_pending_by_session(session_id)
        return {"deleted": True, "session_id": session_id}

    # ---------- 提问 ----------

    def ask(self, query: str, session_id: str | None = None) -> AskResult:
        """提交提问，立即返回。

        不等待结果，不重试。提交前写 pending journal，
        这样 SSE 断流时还能靠 get_answer 找回结果。
        """
        if not query.strip():
            raise ContractError("query 不能为空")
        sid = session_id or str(uuid.uuid4())
        qid = str(uuid.uuid4())

        _append_pending(PendingEntry(sid, qid, query, time.time()))

        drained = False
        try:
            for _ in self.client.stream_chat(query, session_id=sid, query_id=qid):
                drained = True
        except (AuthError,):
            _remove_pending(qid)
            raise
        except LingguangError as exc:
            # 服务端明确报错，说明这次提问没有生效
            _remove_pending(qid)
            raise exc
        except Exception:  # noqa: BLE001
            # 网络层半途断开，提问可能已经到达服务端。
            # 这是"已发出但结果未知"，不是错误，交给 get_answer 去确认。
            return AskResult(sid, qid, status="dispatched_unknown")

        status = "submitted" if drained else "dispatched_unknown"
        return AskResult(sid, qid, status=status)

    def get_answer(
        self,
        query_id: str,
        session_id: str | None = None,
        wait_seconds: int = 0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> dict[str, Any]:
        """取回提问结果。

        实测：任务完成前历史接口里根本没有这一轮，
        完成后一次性以 status=VALID 出现且正文完整。
        所以只需判断"出现了没有"，不用猜"完不完整"。
        """
        wait_seconds = max(0, min(wait_seconds, MAX_WAIT_SECONDS))
        deadline = time.time() + wait_seconds
        attempt = 0
        last_seen_turn: Turn | None = None

        while True:
            turn = self._lookup_turn(query_id, session_id)
            if turn is not None:
                last_seen_turn = turn
                if turn.answer:
                    _remove_pending(query_id)
                    return {
                        "status": AnswerStatus.DONE.value,
                        "session_id": turn.session_id,
                        "query_id": turn.query_id,
                        "text": turn.answer,
                        "tools": turn.tool_titles,
                        "warnings": turn.warnings,
                    }

            if time.time() >= deadline:
                break

            delay = _POLL_DELAYS[min(attempt, len(_POLL_DELAYS) - 1)]
            remaining = deadline - time.time()
            sleep(min(delay, max(remaining, 0.1)))
            attempt += 1

        if last_seen_turn is not None:
            # 出现了但没有正文：很可能在等人工确认
            return {
                "status": AnswerStatus.AWAITING_CONFIRMATION.value,
                "session_id": last_seen_turn.session_id,
                "query_id": query_id,
                "text": "",
                "tools": last_seen_turn.tool_titles,
                "warnings": last_seen_turn.warnings
                + ["该轮已存在但无正文，可能是等待人工确认"],
            }
        return {
            "status": AnswerStatus.PENDING.value,
            "session_id": session_id or "",
            "query_id": query_id,
            "text": "",
            "tools": [],
            "warnings": [],
        }

    def _lookup_turn(self, query_id: str, session_id: str | None) -> Turn | None:
        """先按 session 精确找，找不到再按 pending journal 恢复。"""
        candidate_sessions: list[str] = []
        if session_id:
            candidate_sessions.append(session_id)
        for entry in _read_pending():
            if entry.query_id == query_id and entry.session_id not in candidate_sessions:
                candidate_sessions.append(entry.session_id)

        for sid in candidate_sessions:
            try:
                data = self.client.get_history(sid)
            except LingguangError:
                continue
            turns = pair_turns(data.get("dataList") or [])
            for turn in turns:
                if turn.query_id == query_id:
                    self.sink.upsert_turn(sid, turn, "answer")
                    return turn
        return None

    # ---------- 诊断 ----------

    def auth_status(self) -> dict[str, Any]:
        from .auth import describe_status

        status = describe_status()
        try:
            self.client.login_check()
            mark_ok()
            status["valid"] = True
            status["probe"] = "loginCheck 通过"
        except AuthError as exc:
            mark_error(str(exc))
            status["valid"] = False
            status["probe"] = f"loginCheck 失败: {exc}"
        except LingguangError as exc:
            status["probe"] = f"探测异常: {exc}"
        return status


def _remove_pending_by_session(session_id: str) -> None:
    entries = _read_pending()
    kept = [e for e in entries if e.session_id != session_id]
    if len(kept) == len(entries):
        return
    PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    with PENDING_FILE.open("w", encoding="utf-8") as fh:
        for e in kept:
            fh.write(json.dumps(e.__dict__, ensure_ascii=False) + "\n")
