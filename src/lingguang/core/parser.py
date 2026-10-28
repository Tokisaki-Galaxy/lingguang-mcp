"""artifact 与 cot 双通道解析器。

这是整个工具的生命线。上游改版时，这里第一个崩，也第一个暴露问题。

两条通道：
  A. artifact：templateData.text 是一段 HTML，正文以
     <script>AgentEventRenderer.render({...})</script> 事件流内嵌其中，
     取 turn/finalResponse/delta 的 params.delta 拼接，剥标签得明文。
  B. cot：templateData.cot 是两层 JSON 编码，
     取 item/tool/start 的 display.title 拿工具轨迹，
     取 item/agentMessage/delta 拿过程话术。

三条设计原则：
  1. 对未知事件宽容。上游加新 method 是常态，不能因此让整个工具崩。
  2. 断言分级。结构缺失抛 ContractError，结构在但内容可疑加 warnings。
  3. 原始样本必须留存，否则出问题无从排查。
"""

from __future__ import annotations

import html as html_mod
import json
import re
from typing import Any

from .errors import ContractError
from .models import ToolCall, Turn

# AgentEventRenderer.render({...});  —— 贪婪匹配内层对象
_RENDER_RE = re.compile(
    r"AgentEventRenderer\.render\((\{.*?\})\);</script>", re.DOTALL
)

# 已知的、对解析有意义的 cot 方法
_KNOWN_COT_METHODS = frozenset(
    {
        "turn/start",
        "turn/finish",
        "item/agentMessage/start",
        "item/agentMessage/delta",
        "item/agentMessage/finish",
        "item/toolgroup/start",
        "item/toolgroup/finish",
        "item/tool/start",
        "item/tool/finish",
    }
)

# 正文短于这个长度、且带工具轨迹时，判为可疑
_SUSPICIOUS_SHORT_TEXT = 50


def _iter_render_events(raw_html: str) -> list[dict[str, Any]]:
    """从 artifact HTML 里抽出所有 render 事件。解析失败的片段跳过。"""
    events: list[dict[str, Any]] = []
    for m in _RENDER_RE.finditer(raw_html):
        try:
            ev = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(ev, dict):
            events.append(ev)
    return events


def _strip_html(fragment: str) -> str:
    """把 delta 里的 HTML 片段转成纯文本。"""
    text = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.IGNORECASE)
    text = re.sub(
        r"</p>|</li>|</h[1-6]>|</tr>|</div>", "\n", text, flags=re.IGNORECASE
    )
    text = re.sub(r"<[^>]+>", "", text)
    text = html_mod.unescape(text)
    lines = [ln.strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def parse_artifact_text(raw_html: str) -> str:
    """通道 A：从 artifact 提取正文。

    实测样本里 finalResponse/delta 是唯一承载正文的方法。
    有些回复（比如纯文本寒暄）也会走这条通道，只是 delta 很短。
    """
    if not raw_html:
        return ""
    head = raw_html.lstrip()[:20].lower()
    if not head.startswith("<!doctype") and not head.startswith("<html"):
        # 已经是纯文本或 markdown，直接返回
        return raw_html.strip()

    parts: list[str] = []
    for ev in _iter_render_events(raw_html):
        if ev.get("method") != "turn/finalResponse/delta":
            continue
        delta = (ev.get("params") or {}).get("delta")
        if isinstance(delta, str) and delta:
            parts.append(delta)
    if not parts:
        return ""
    return _strip_html("".join(parts))


def parse_artifact_events(raw_html: str) -> list[dict[str, Any]]:
    """取出 artifact 里全部事件，用于工具轨迹和未知事件检测。"""
    return _iter_render_events(raw_html)


def _decode_cot(cot_raw: str) -> list[dict[str, Any]]:
    """cot 是两层 JSON 编码：外层是 {content: "..."}，content 里才是数组。"""
    if not cot_raw:
        return []
    try:
        outer = json.loads(cot_raw)
    except json.JSONDecodeError as exc:
        raise ContractError("cot 外层 JSON 解析失败", sample=cot_raw) from exc
    if not isinstance(outer, dict):
        raise ContractError("cot 外层不是对象", sample=cot_raw)

    inner = outer.get("content")
    if isinstance(inner, str):
        try:
            inner = json.loads(inner)
        except json.JSONDecodeError as exc:
            raise ContractError("cot 内层 JSON 解析失败", sample=inner) from exc
    if inner is None:
        return []
    if not isinstance(inner, list):
        raise ContractError("cot content 不是数组", sample=str(inner))
    return [e for e in inner if isinstance(e, dict)]


def parse_cot_tools(cot_raw: str) -> list[ToolCall]:
    """通道 B：从 cot 提取工具调用轨迹。"""
    tools: list[ToolCall] = []
    seen: set[str] = set()
    for ev in _decode_cot(cot_raw):
        if ev.get("method") != "item/tool/start":
            continue
        params = ev.get("params") or {}
        display = params.get("display") or {}
        title = display.get("title")
        if not isinstance(title, str) or not title:
            continue
        item_id = str(params.get("itemId") or "")
        key = item_id or title
        if key in seen:
            continue
        seen.add(key)
        tools.append(
            ToolCall(
                title=title,
                item_id=item_id,
                group_id=str(params.get("groupId") or ""),
            )
        )
    return tools


def parse_cot_agent_deltas(cot_raw: str) -> list[str]:
    """通道 B：提取 Agent 的过程话术（开场白等）。"""
    out: list[str] = []
    for ev in _decode_cot(cot_raw):
        if ev.get("method") != "item/agentMessage/delta":
            continue
        delta = (ev.get("params") or {}).get("delta")
        if isinstance(delta, str) and delta:
            out.append(delta)
    return out


def collect_unknown_events(cot_raw: str, artifact_events: list[dict[str, Any]]) -> list[str]:
    """收集未知事件类型。

    这是宽容策略的核心：上游加新 method 时不崩，但要让调用方知道。
    返回去重后的 method 名列表。
    """
    unknown: set[str] = set()
    for ev in _decode_cot(cot_raw):
        method = ev.get("method")
        if isinstance(method, str) and method and method not in _KNOWN_COT_METHODS:
            unknown.add(method)
    known_artifact = {
        "turn/start",
        "turn/finalResponse/start",
        "turn/finalResponse/delta",
        "turn/finalResponse/finish",
        "turn/finish",
    }
    for ev in artifact_events:
        method = ev.get("method")
        if isinstance(method, str) and method and method not in known_artifact:
            unknown.add(method)
    return sorted(unknown)


def build_turn(session_id: str, item: dict[str, Any], query: str = "") -> Turn:
    """把一个历史接口返回的 ANSWER 条目解析成 Turn。

    断言分级在这里落地：
      必填结构缺失 -> ContractError
      结构在但内容可疑 -> warnings
    """
    if not isinstance(item, dict):
        raise ContractError("历史条目不是对象", sample=str(item)[:500])

    template = item.get("templateData")
    if template is None:
        raise ContractError(
            "历史条目缺少 templateData", sample=json.dumps(item, ensure_ascii=False)[:500]
        )
    if not isinstance(template, dict):
        raise ContractError("templateData 不是对象", sample=str(template)[:500])

    raw_text = template.get("text") or ""
    cot_raw = template.get("cot") or ""

    warnings: list[str] = []

    artifact_events = parse_artifact_events(raw_text)
    answer = parse_artifact_text(raw_text)
    tools = parse_cot_tools(cot_raw)
    deltas = parse_cot_agent_deltas(cot_raw)

    unknown = collect_unknown_events(cot_raw, artifact_events)
    if unknown:
        warnings.append("未知事件类型: " + ", ".join(unknown))

    # 结构在但内容可疑的几种判定
    if cot_raw and not tools:
        # cot 存在却零工具事件。账单类问题本该有轨迹，寒暄类本来就没有，
        # 所以这里不判错，只提示。
        if any(k in answer for k in ("查询", "账单", "统计", "读取", "核对")):
            warnings.append("cot 存在但未解析出工具事件，正文却提及查询类动作")

    if answer and len(answer) < _SUSPICIOUS_SHORT_TEXT and tools:
        warnings.append(f"正文异常短（{len(answer)} 字符）但带 {len(tools)} 条工具轨迹")

    if raw_text and not answer:
        warnings.append("artifact 存在但未提取到正文，可能是未知的渲染格式")

    return Turn(
        session_id=session_id,
        query_id=str(item.get("queryId") or ""),
        query=query,
        answer=answer,
        tools=tools,
        agent_deltas=deltas,
        status=str(item.get("status") or ""),
        created_at=int(item.get("time") or 0),
        raw_text=raw_text,
        warnings=warnings,
    )


def pair_turns(items: list[dict[str, Any]]) -> list[Turn]:
    """把历史条目里的 QUERY 和 ANSWER 配对成 Turn 列表。

    实测返回顺序是 QUERY, ANSWER, QUERY, ANSWER 交替，
    但按 queryId 配对更稳妥。
    """
    queries: dict[str, str] = {}
    answers: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    for item in items:
        if not isinstance(item, dict):
            continue
        qid = str(item.get("queryId") or "")
        kind = item.get("itemType")
        if kind == "QUERY":
            queries[qid] = str(item.get("query") or "")
            if qid not in order:
                order.append(qid)
        elif kind == "ANSWER":
            answers[qid] = item
            if qid not in order:
                order.append(qid)

    turns: list[Turn] = []
    for qid in order:
        item = answers.get(qid)
        if item is None:
            continue
        sid = str(item.get("sessionId") or "")
        turns.append(build_turn(sid, item, query=queries.get(qid, "")))
    return turns