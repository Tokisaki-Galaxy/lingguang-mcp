"""解析器测试。这是回归保护的第一道防线。

fixture 全部来自真实抓包，只做字面脱敏，结构保持原样。
上游改版时，这里应该第一个亮红灯。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lingguang.core.errors import ContractError
from lingguang.core.parser import (
    build_turn,
    collect_unknown_events,
    pair_turns,
    parse_artifact_text,
    parse_cot_agent_deltas,
    parse_cot_tools,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> tuple[str, str]:
    html = (FIXTURES / f"{name}.raw.html").read_text(encoding="utf-8")
    cot = (FIXTURES / f"{name}.cot.json").read_text(encoding="utf-8")
    return html, cot


class TestArtifactParsing:
    def test_billing_report_extracts_text(self) -> None:
        html, _ = _load("answer_billing")
        text = parse_artifact_text(html)
        assert text, "账单报告应能提取出正文"
        assert len(text) > 200
        # 账单报告的首行是一句结论
        assert "月" in text

    def test_plain_reply(self) -> None:
        html, _ = _load("answer_plain")
        text = parse_artifact_text(html)
        assert text
        assert len(text) < 100

    def test_multi_tool_report(self) -> None:
        html, _ = _load("answer_multi_tool")
        text = parse_artifact_text(html)
        assert text
        assert len(text) > 200

    def test_empty_input(self) -> None:
        assert parse_artifact_text("") == ""

    def test_plain_markdown_passthrough(self) -> None:
        # 非 HTML 的纯文本应原样返回
        assert parse_artifact_text("这是一段纯文本") == "这是一段纯文本"

    def test_html_without_render_events(self) -> None:
        html = "<!DOCTYPE html><html><body><p>无事件</p></body></html>"
        assert parse_artifact_text(html) == ""

    def test_strips_html_entities(self) -> None:
        html, _ = _load("answer_billing")
        text = parse_artifact_text(html)
        assert "&lt;" not in text
        assert "&amp;" not in text


class TestCotParsing:
    def test_extracts_tool_titles(self) -> None:
        _, cot = _load("answer_billing")
        tools = parse_cot_tools(cot)
        assert len(tools) >= 2
        assert all(t.title for t in tools)

    def test_tools_deduplicated(self) -> None:
        _, cot = _load("answer_billing")
        tools = parse_cot_tools(cot)
        item_ids = [t.item_id for t in tools if t.item_id]
        assert len(item_ids) == len(set(item_ids))

    def test_plain_answer_has_no_tools(self) -> None:
        _, cot = _load("answer_plain")
        assert parse_cot_tools(cot) == []

    def test_agent_deltas(self) -> None:
        _, cot = _load("answer_billing")
        deltas = parse_cot_agent_deltas(cot)
        assert deltas
        assert all(isinstance(d, str) for d in deltas)

    def test_empty_cot(self) -> None:
        assert parse_cot_tools("") == []
        assert parse_cot_agent_deltas("") == []

    def test_malformed_cot_raises_contract_error(self) -> None:
        with pytest.raises(ContractError):
            parse_cot_tools("这不是 JSON")


class TestUnknownEventTolerance:
    def test_unknown_events_reported_not_raised(self) -> None:
        html, cot = _load("answer_unknown_event")
        unknown = collect_unknown_events(cot, [])
        assert "item/futureThing/start" in unknown

    def test_unknown_does_not_break_tool_parsing(self) -> None:
        _, cot = _load("answer_unknown_event")
        tools = parse_cot_tools(cot)
        assert len(tools) == 1
        assert tools[0].title == "示例工具"

    def test_known_events_not_reported(self) -> None:
        _, cot = _load("answer_plain")
        unknown = collect_unknown_events(cot, [])
        assert unknown == []


class TestBuildTurn:
    def _make_item(self, name: str, query: str = "测试问题") -> dict:
        html, cot = _load(name)
        return {
            "itemType": "ANSWER",
            "queryId": "q-test-1",
            "sessionId": "s-test-1",
            "status": "VALID",
            "time": 1700000000000,
            "templateData": {"text": html, "cot": cot},
        }

    def test_builds_complete_turn(self) -> None:
        turn = build_turn("s-test-1", self._make_item("answer_billing"), query="查账单")
        assert turn.session_id == "s-test-1"
        assert turn.query_id == "q-test-1"
        assert turn.query == "查账单"
        assert turn.answer
        assert turn.tool_titles
        assert turn.status == "VALID"

    def test_missing_template_raises(self) -> None:
        with pytest.raises(ContractError):
            build_turn("s", {"itemType": "ANSWER"})

    def test_template_not_dict_raises(self) -> None:
        with pytest.raises(ContractError):
            build_turn("s", {"templateData": "字符串"})

    def test_empty_text_adds_warning(self) -> None:
        item = {
            "queryId": "q1",
            "sessionId": "s1",
            "templateData": {"text": "<!DOCTYPE html><html><body></body></html>", "cot": ""},
        }
        turn = build_turn("s1", item)
        assert turn.warnings
        assert any("未提取到正文" in w for w in turn.warnings)

    def test_short_text_with_tools_warns(self) -> None:
        cot = json.dumps(
            {
                "content": json.dumps(
                    [
                        {
                            "method": "item/tool/start",
                            "params": {"itemId": "t1", "display": {"title": "某工具"}},
                        }
                    ]
                )
            }
        )
        html = (
            '<!DOCTYPE html><html><body><script>AgentEventRenderer.render('
            '{"method":"turn/finalResponse/delta","params":{"delta":"短"}}'
            ");</script></body></html>"
        )
        item = {"queryId": "q1", "sessionId": "s1", "templateData": {"text": html, "cot": cot}}
        turn = build_turn("s1", item)
        assert any("正文异常短" in w for w in turn.warnings)

    def test_unknown_event_adds_warning(self) -> None:
        turn = build_turn("s1", self._make_item("answer_unknown_event"))
        assert any("未知事件类型" in w for w in turn.warnings)


class TestPairTurns:
    def test_pairs_query_and_answer(self) -> None:
        items = [
            {"itemType": "QUERY", "queryId": "q1", "query": "问题一"},
            {
                "itemType": "ANSWER",
                "queryId": "q1",
                "sessionId": "s1",
                "templateData": {"text": "纯文本回答", "cot": ""},
            },
        ]
        turns = pair_turns(items)
        assert len(turns) == 1
        assert turns[0].query == "问题一"
        assert turns[0].answer == "纯文本回答"

    def test_keeps_orphan_answer(self) -> None:
        """孤立回答要保留。

        分页拉取时 QUERY 可能落在上一页，丢弃会丢数据。
        query 字段留空即可，正文和工具轨迹仍有价值。
        """
        items = [
            {
                "itemType": "ANSWER",
                "queryId": "q-orphan",
                "sessionId": "s1",
                "templateData": {"text": "孤立回答", "cot": ""},
            }
        ]
        turns = pair_turns(items)
        assert len(turns) == 1
        assert turns[0].answer == "孤立回答"
        assert turns[0].query == ""

    def test_preserves_order(self) -> None:
        items = [
            {"itemType": "QUERY", "queryId": "q1", "query": "一"},
            {"itemType": "ANSWER", "queryId": "q1", "sessionId": "s", "templateData": {"text": "甲", "cot": ""}},
            {"itemType": "QUERY", "queryId": "q2", "query": "二"},
            {"itemType": "ANSWER", "queryId": "q2", "sessionId": "s", "templateData": {"text": "乙", "cot": ""}},
        ]
        turns = pair_turns(items)
        assert [t.query for t in turns] == ["一", "二"]

    def test_empty_input(self) -> None:
        assert pair_turns([]) == []
