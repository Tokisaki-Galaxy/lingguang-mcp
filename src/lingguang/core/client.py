"""HTTP 传输层。

只负责收发和协议正确的编解码，不含业务判断。
所有接口签名都来自 2026-10-28 的实测抓包。

三个必须遵守的实测约束：
  1. sceneCode 分两套：历史/删除用 LEOPARD，提问用 WEB
  2. pageSize 上限 30，31 直接 SYSTEM_ERROR
  3. SSE 不能按行读，单行可能超长且含多字节 UTF-8，必须按字节切 \\n\\n
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Iterator

import requests

from .errors import AuthError, ContractError, RateLimitError, TransportError

BASE = "https://cognihome.lingguang.com"
ORIGIN = "https://www.lingguang.com"
APP_ID = "202609150201453629925"

# 两套场景值，不能统一
SCENE_HISTORY = "LEOPARD"
SCENE_CHAT = "WEB"

MAX_PAGE_SIZE = 30
DEFAULT_TIMEOUT = 30

# 会话已失效或登录态丢失时服务端常见的返回码
_SYSTEM_ERROR = "SYSTEM_ERROR"
_INVALID_PARAMETER = "INVALID_PARAMETER"


class HttpClient:
    def __init__(self, cookie: str, timeout: int = DEFAULT_TIMEOUT) -> None:
        self.session = requests.Session()
        self.timeout = timeout
        self.ctoken = self._extract_ctoken(cookie)
        if not self.ctoken:
            raise AuthError("cookie 里找不到 ctoken，请重新导入")
        self.session.headers.update(
            {
                "content-type": "application/json",
                "accept": "application/json, text/plain, */*",
                "origin": ORIGIN,
                "referer": ORIGIN + "/",
                "cookie": cookie.strip(),
                "user-agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36 Edg/156.0.0.0"
                ),
            }
        )

    @staticmethod
    def _extract_ctoken(cookie: str) -> str:
        for part in cookie.split(";"):
            name, _, value = part.strip().partition("=")
            if name == "ctoken":
                return value.strip()
        return ""

    # ---------- 基础设施 ----------

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{BASE}{path}?ctoken={self.ctoken}"
        try:
            resp = self.session.post(url, data=json.dumps(payload), timeout=self.timeout)
        except requests.RequestException as exc:
            raise TransportError(f"请求 {path} 失败: {exc}") from exc

        if resp.status_code == 429:
            raise RateLimitError(f"{path} 被限流，请降低频率")
        if resp.status_code in (401, 403):
            raise AuthError(f"{path} 返回 {resp.status_code}，cookie 可能已失效")

        try:
            data = resp.json()
        except ValueError as exc:
            raise ContractError(f"{path} 返回的不是 JSON", sample=resp.text) from exc

        if not isinstance(data, dict):
            raise ContractError(f"{path} 返回结构不是对象", sample=resp.text)

        if not data.get("success"):
            code = str(data.get("code") or "")
            msg = str(data.get("msg") or "")
            if code == _SYSTEM_ERROR and "pageSize" in msg.lower():
                raise ContractError(f"{path} pageSize 超限", sample=resp.text)
            if code == _INVALID_PARAMETER:
                raise ContractError(f"{path} 参数非法: {msg}", sample=resp.text)
            raise ContractError(f"{path} 返回失败: {code} {msg}", sample=resp.text)
        return data

    # ---------- 会话 ----------

    def list_sessions(
        self, page_size: int = MAX_PAGE_SIZE, cursor: int | None = None
    ) -> dict[str, Any]:
        page_size = min(page_size, MAX_PAGE_SIZE)
        data = self._post_json(
            "/chat/queryHistoryChatSession.json",
            {
                "sceneCode": SCENE_HISTORY,
                "latestTime": cursor,
                "pageSize": page_size,
                "ctoken": self.ctoken,
            },
        )
        return data

    def get_history(self, session_id: str, page_size: int = MAX_PAGE_SIZE) -> dict[str, Any]:
        page_size = min(page_size, MAX_PAGE_SIZE)
        return self._post_json(
            "/chat/queryHistoryChatContent.json",
            {
                "sessionId": session_id,
                "sceneCode": SCENE_HISTORY,
                "latestTime": None,
                "pageSize": page_size,
                "ctoken": self.ctoken,
            },
        )

    def delete_session(self, session_id: str, scene: str = SCENE_HISTORY) -> dict[str, Any]:
        """删除会话。

        实测重要约束：sceneCode 必须与会话自身的来源场景一致，
        否则接口返回 SUCCESS 但静默什么都不删。
        LEOPARD 会话要传 LEOPARD，WEB 会话要传 WEB。
        """
        return self._post_json(
            "/chat/deleteChatSession.json",
            {
                "sessionId": session_id,
                "sceneCode": scene,
                "ctoken": self.ctoken,
            },
        )

    def find_session_scene(self, session_id: str) -> str | None:
        """查会话的来源场景，删不掉时用来排查。"""
        data = self.list_sessions(page_size=MAX_PAGE_SIZE)
        for item in data.get("dataList") or []:
            if item.get("sessionId") == session_id:
                return str(item.get("sceneCode") or SCENE_HISTORY)
        return None

    def session_exists(self, session_id: str) -> bool:
        return self.find_session_scene(session_id) is not None

    def login_check(self) -> dict[str, Any]:
        return self._post_json("/user/loginCheck.json", {"ctoken": self.ctoken})

    # ---------- 提问 ----------

    def build_chat_payload(self, query: str, session_id: str, query_id: str) -> dict[str, Any]:
        return {
            "query": query,
            "attachmentList": [],
            "extParams": {
                "clientTheme": "light",
                "appId": APP_ID,
                "queryHint": "",
                "locationAuthStatus": "NOT_DETERMINED",
                "location": "",
            },
            "queryId": query_id,
            "queryType": "text_input",
            "sessionId": session_id,
            "sceneCode": SCENE_CHAT,
        }

    def stream_chat(
        self,
        query: str,
        session_id: str | None = None,
        query_id: str | None = None,
        idle_timeout: int = DEFAULT_TIMEOUT,
    ) -> Iterator[dict[str, Any]]:
        """发起提问，逐条 yield SSE 事件。

        session_id 为 None 时自动生成 UUID。实测服务端会直接采用客户端给的
        session_id 建新会话，传空串或省略字段才会 500。

        用 iter_content 自己切帧，不用 iter_lines：
        SSE 单行可能远超默认缓冲区且含多字节 UTF-8，
        iter_lines 会截断并产生乱码。
        """
        sid = session_id or str(uuid.uuid4())
        qid = query_id or str(uuid.uuid4())
        url = f"{BASE}/chat/stream_chat?ctoken={self.ctoken}"
        payload = self.build_chat_payload(query, sid, qid)
        headers = {"accept": "text/event-stream"}

        try:
            resp = self.session.post(
                url,
                data=json.dumps(payload),
                headers=headers,
                stream=True,
                timeout=idle_timeout,
            )
        except requests.RequestException as exc:
            raise TransportError(f"提问请求失败: {exc}") from exc

        if resp.status_code == 429:
            raise RateLimitError("提问被限流")
        if resp.status_code in (401, 403):
            raise AuthError(f"提问返回 {resp.status_code}，cookie 可能已失效")
        if resp.status_code >= 500:
            raise ContractError(f"提问返回 {resp.status_code}", sample=resp.text[:500])

        content_type = resp.headers.get("content-type", "")
        if "event-stream" not in content_type:
            raise ContractError(
                f"提问返回的不是 SSE（{content_type}）", sample=resp.text[:500]
            )

        buffer = b""
        try:
            for chunk in resp.iter_content(chunk_size=None):
                if not chunk:
                    continue
                buffer += chunk
                while b"\n\n" in buffer:
                    frame, _, buffer = buffer.partition(b"\n\n")
                    event = self._parse_frame(frame)
                    if event is not None:
                        yield event
            if buffer.strip():
                event = self._parse_frame(buffer)
                if event is not None:
                    yield event
        finally:
            resp.close()

    @staticmethod
    def _parse_frame(frame: bytes) -> dict[str, Any] | None:
        data_lines: list[bytes] = []
        for raw in frame.split(b"\n"):
            line = raw.rstrip(b"\r")
            if line.startswith(b"data:"):
                data_lines.append(line[5:])
        if not data_lines:
            return None
        joined = b"\n".join(data_lines)
        try:
            decoded = joined.decode("utf-8")
        except UnicodeDecodeError:
            return None
        try:
            event = json.loads(decoded)
        except json.JSONDecodeError:
            return None
        return event if isinstance(event, dict) else None
