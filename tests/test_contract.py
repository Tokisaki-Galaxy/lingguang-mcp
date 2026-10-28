"""契约测试。打真实接口，只断言结构不断言内容。

默认跳过，需要显式加 -m live 并且提供 LG_COOKIE 或已导入凭据。

这一层的价值：上游改版时第一时间发现。
不要在这里断言具体的金额、商户名，那些会变。
"""

from __future__ import annotations

import os
import time
import uuid

import pytest

from lingguang.core.errors import LingguangError
from lingguang.core.service import Service

pytestmark = pytest.mark.live

E2E_PREFIX = "[e2e-test]"


def _has_credentials() -> bool:
    if os.environ.get("LG_COOKIE"):
        return True
    from lingguang.core import storage

    return storage.load() is not None


requires_live = pytest.mark.skipif(
    not _has_credentials(), reason="需要真实 cookie"
)


def _service() -> Service:
    return Service()


@requires_live
def test_list_sessions_contract() -> None:
    svc = _service()
    data = svc.list_sessions(limit=30)
    assert "sessions" in data
    assert "next_cursor" in data
    for s in data["sessions"]:
        assert s["id"]
        assert "summary" in s
        assert s["scene"] in ("LEOPARD", "WEB")


@requires_live
def test_history_contract() -> None:
    svc = _service()
    sessions = svc.list_sessions(limit=1)["sessions"]
    if not sessions:
        pytest.skip("没有会话可测")
    data = svc.get_transcript(sessions[0]["id"])
    assert "turns" in data
    assert "count" in data


@requires_live
def test_new_session_creation_regression() -> None:
    """关键回归：ask 不带 session_id 必须能建出会话。

    这是整个工具最容易被上游改动破坏的能力。
    测试会话带 [e2e-test] 前缀，结束后自动清理，不污染真实数据。
    """
    svc = _service()
    result = svc.ask(f"{E2E_PREFIX} 只回复：好的", session_id=None)
    try:
        assert result.session_id
        assert len(result.session_id) == 36  # UUID 形态
        answer = svc.get_answer(
            result.query_id, session_id=result.session_id, wait_seconds=50
        )
        assert answer["status"] in ("done", "pending", "awaiting_confirmation")
    finally:
        svc.delete_session(result.session_id, confirm=True)


@requires_live
def test_delete_is_idempotent() -> None:
    svc = _service()
    fake_id = str(uuid.uuid4())
    out = svc.delete_session(fake_id, confirm=True)
    assert out["deleted"] is True


@requires_live
def test_page_size_upper_bound() -> None:
    """pageSize 超过 30 时应在客户端就被截断，不应打到服务端报错。"""
    svc = _service()
    sessions = svc.list_sessions(limit=1)["sessions"]
    if not sessions:
        pytest.skip("没有会话")
    # limit=99 应被截断到 30，正常返回
    data = svc.get_transcript(sessions[0]["id"], limit=99)
    assert data["count"] >= 0
