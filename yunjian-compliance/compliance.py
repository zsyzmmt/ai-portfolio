# -*- coding: utf-8 -*-
"""
合规风险检测引擎
================
在员工言论中扫描「合规风险词库」（compliance_rules.py），
识别命中的风险类别，并给出对应的整改建议。

输出结构（每条命中）：
  {
    "category":   风险类别，如 "违规承诺收益"
    "severity":   风险等级：高 / 中 / 低
    "matched":    命中的触发词列表
    "suggestion": 整改建议
  }
"""
import json
import os

from compliance_rules import COMPLIANCE_RULES

# 运行时自定义词库：compliance_custom.py（由"词库提炼-应用"生成，不破坏内置词库）
_CUSTOM_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "compliance_custom.py")


def _load_custom():
    """读取自定义词库 {类别: [词, ...]}。"""
    try:
        ns = {}
        with open(_CUSTOM_PATH, "r", encoding="utf-8") as fh:
            exec(compile(fh.read(), _CUSTOM_PATH, "exec"), ns)
        return ns.get("CUSTOM_KEYWORDS", {}) or {}
    except (OSError, SyntaxError):
        return {}


def _merged_rules():
    """合并内置 + 自定义词库，返回最终规则字典。"""
    rules = {k: dict(v) for k, v in COMPLIANCE_RULES.items()}
    for cat, words in _load_custom().items():
        if cat in rules:
            rules[cat]["keywords"] = list(dict.fromkeys(rules[cat]["keywords"] + words))
        else:
            # 自定义类别：默认中等风险
            rules[cat] = {"severity": "中", "keywords": list(words),
                          "suggestion": "新增自定义合规类别，请补充整改建议。"}
    return rules


def detect(text):
    """扫描一段员工言论，返回命中的合规风险列表。"""
    text = (text or "").strip()
    if not text:
        return []

    hits = []
    for category, rule in _merged_rules().items():
        matched = [kw for kw in rule["keywords"] if kw in text]
        if matched:
            hits.append({
                "category": category,
                "severity": rule["severity"],
                "matched": matched,
                "suggestion": rule["suggestion"],
            })
    return hits


def summarize(hits):
    """把多条命中汇总为简洁结论，便于展示与报告。"""
    if not hits:
        return None
    categories = [h["category"] for h in hits]
    high_count = sum(1 for h in hits if h["severity"] == "高")
    if high_count:
        return "发现 %d 项合规风险，其中 %d 项高风险（%s）" % (
            len(hits), high_count, "、".join(categories))
    return "发现 %d 项合规风险（%s）" % (len(hits), "、".join(categories))
