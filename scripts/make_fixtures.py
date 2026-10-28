"""从真实抓包生成脱敏 fixture。

原则：只做字面替换，不重排缩进、不改结构。
标签结构、类名、delta 分段方式本身携带上游版本信息，
重排会让 fixture 失去回归价值。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lingguang"))

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

# 只替换真实个人信息的字面量，保持长度相近以便结构不变形
REPLACEMENTS = [
    ("金掌柜脆皮鸡米饭", "示例商户A"),
    ("金掌柜", "示例商户A"),
    ("董记隆江猪脚饭", "示例商户B"),
    ("米饭先生", "示例商户C"),
    ("李小胖秘制酱骨饭", "示例商户D"),
    ("拼多多", "电商平台甲"),
    ("盒马", "超市平台乙"),
    ("韩镒名", "某管理员"),
    ("邮箱探针", "示例群聊"),
    ("边际实验室", "示例群组二"),
    ("工作通知群", "示例群组三"),
    # 个人生活细节
    ("水卡", "校园卡"),
    ("考研统考报名费", "考试报名费"),
    ("考研", "考试"),
    ("食堂", "校内餐厅"),
    ("宿舍", "住处"),
    ("花呗", "信用付款"),
]


def desensitize(text: str) -> str:
    out = text
    for raw, repl in REPLACEMENTS:
        out = out.replace(raw, repl)

    # 金额替换：只处理明确的「数字.数字 元」形态，保留数字位宽
    out = re.sub(r"\b\d{1,4}\.\d{2}(?= ?元)", "00.00", out)
    # 正文里的独立金额（如「花了 2077.40」「支出 466.85」），保留两位小数形态
    out = re.sub(r"(?<![\d.])\d{2,5}\.\d{2}(?![\d])", "00.00", out)
    # 整数金额，如「150 元」「50 元」
    out = re.sub(r"(?<![\d.])\d{1,5}(?= ?元)", "000", out)
    # delta 分段推送会把金额切开，残留的「.50 元」这类小数片段
    out = re.sub(r"(?<=\")\.\d{2}(?= ?元)", ".00", out)

    # UUID 替换：保持格式，避免破坏 JSON 结构和长度判断
    out = re.sub(
        r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b",
        "00000000-0000-0000-0000-000000000000",
        out,
    )

    # 长串数字（订单号、账号）替换，但不碰 timestamp 这类 13 位时间戳字段
    out = re.sub(r'"timestamp(?:Ms)?":\s*"?\d+"?', '"timestamp":0', out)
    out = re.sub(r"\b1\d{12}\b", "0000000000000", out)
    return out


def build_fixture(answer_item: dict, name: str) -> None:
    template = answer_item.get("templateData") or {}
    raw_html = template.get("text") or ""
    cot = template.get("cot") or ""

    FIXTURES.mkdir(exist_ok=True)
    (FIXTURES / f"{name}.raw.html").write_text(desensitize(raw_html), encoding="utf-8")
    (FIXTURES / f"{name}.cot.json").write_text(cot, encoding="utf-8")


def main() -> None:
    src = Path(sys.argv[1])
    data = json.loads(src.read_text(encoding="utf-8"))
    items = data.get("dataList") or []

    buckets: dict[str, dict] = {}
    for item in items:
        if item.get("itemType") != "ANSWER":
            continue
        template = item.get("templateData") or {}
        text = template.get("text") or ""
        cot = template.get("cot") or ""
        tool_count = cot.count("item/tool/start")
        if tool_count == 0 and len(text) < 12000:
            key = "answer_plain"
        elif tool_count == 0:
            key = "answer_notools"
        elif tool_count >= 4 and not (FIXTURES / "answer_billing.raw.html").exists():
            key = "answer_billing"
        elif tool_count >= 2 and not (FIXTURES / "answer_multi_tool.raw.html").exists():
            key = "answer_multi_tool"
        else:
            continue
        if key not in buckets:
            buckets[key] = item

    for key, item in buckets.items():
        build_fixture(item, key)
        print(f"生成 {key}")

    # 未知事件类型的合成样本
    synthetic_cot = json.dumps(
        {
            "content": json.dumps(
                [
                    {"method": "turn/start", "params": {}},
                    {"method": "item/futureThing/start", "params": {"x": 1}},
                    {"method": "item/tool/start", "params": {"itemId": "t1", "display": {"title": "示例工具"}}},
                    {"method": "turn/finish", "params": {}},
                ]
            )
        }
    )
    FIXTURES.mkdir(exist_ok=True)
    (FIXTURES / "answer_unknown_event.cot.json").write_text(synthetic_cot, encoding="utf-8")
    (FIXTURES / "answer_unknown_event.raw.html").write_text(
        "<!DOCTYPE html><html><body><div id=\"render-root\"></div></body></html>",
        encoding="utf-8",
    )
    print("生成 answer_unknown_event")


if __name__ == "__main__":
    main()
