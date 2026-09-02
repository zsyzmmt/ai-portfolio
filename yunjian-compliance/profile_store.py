# -*- coding: utf-8 -*-
"""
员工风险档案存储
================
批量分析成功后，按"姓名"累计每位员工的风险档案：
  - 违规次数   （命中合规风险的言论条数）
  - 高风险次数 （等级=高的违规次数）
  - 涉及合规类别分布
  - 风险走势   （最近若干次分析的负面风险分，用于预警）

档案持久化在 data/profiles.json，跨批次累计，实现"重点人员持续监测预警"。
"""
import json
import os

MAX_HISTORY = 12   # 每位员工保留最近 N 次分析的风险分


def _path():
    base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "data", "profiles.json")


def load_profiles():
    """读取档案。文件缺失/损坏时返回空档案。"""
    try:
        with open(_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict) or "employees" not in data:
            raise ValueError
        return data
    except (OSError, ValueError):
        return {"updated_at": "", "sessions": 0, "employees": {}}


def save_profiles(data):
    os.makedirs(os.path.dirname(_path()), exist_ok=True)
    with open(_path(), "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    return _path()


def update_from_items(analyzed, session_date):
    """把一批分析结果累计进员工档案。

    analyzed 来自 batch.analyze_batch()；session_date 形如 "2026-08-07"。
    每次会话每位员工只追加一条走势记录（取本次会话最高风险分）。
    """
    data = load_profiles()
    data["updated_at"] = session_date
    data["sessions"] = data.get("sessions", 0) + 1
    emps = data["employees"]

    # 先按姓名聚合本次会话
    sessions = {}
    for x in analyzed:
        name = (x.get("name") or "").strip()
        if not name:
            continue
        s = sessions.setdefault(name, {
            "rows": 0, "violations": 0, "high": 0, "max_risk": 0,
            "cats": {}, "branch": "",
        })
        s["rows"] += 1
        if x.get("group"):
            s["branch"] = x["group"]
        if x.get("categories"):
            s["violations"] += 1
        if x.get("has_high"):
            s["high"] += 1
        s["max_risk"] = max(s["max_risk"], x.get("risk") or 0)
        for cat in x.get("categories") or []:
            s["cats"][cat] = s["cats"].get(cat, 0) + 1

    for name, s in sessions.items():
        p = emps.setdefault(name, {
            "name": name, "branch": "", "rows": 0, "violations": 0,
            "high_rows": 0, "categories": {}, "latest_risk": 0, "history": [],
        })
        p["rows"] += s["rows"]
        p["violations"] += s["violations"]
        p["high_rows"] += s["high"]
        if s["branch"]:
            p["branch"] = s["branch"]
        for cat, n in s["cats"].items():
            p["categories"][cat] = p["categories"].get(cat, 0) + n
        p["latest_risk"] = s["max_risk"]
        p["history"].append({"d": session_date, "r": s["max_risk"], "v": s["violations"]})
        p["history"] = p["history"][-MAX_HISTORY:]

    data["employees"] = emps
    save_profiles(data)
    return data


def reset_profiles():
    """清空全部员工档案。"""
    save_profiles({"updated_at": "", "sessions": 0, "employees": {}})


def ranked(limit=12):
    """按违规次数（其次高风险次数、最近风险分）排序，返回 (档案, 排序列表)。"""
    data = load_profiles()
    emps = list(data["employees"].values())
    emps.sort(key=lambda p: (-p["violations"], -p["high_rows"], -p["latest_risk"]))
    return data, emps[:limit]
