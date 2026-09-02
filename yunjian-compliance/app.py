# -*- coding: utf-8 -*-
"""
员工信息负面检测 - 网页应用
================================
启动：C:\\Python3\\python.exe app.py
然后浏览器打开 http://127.0.0.1:5000

功能：
  - 粘贴或上传员工中文信息（文本 / 图片）
  - 文本 → 情感分析（负面风险打分）
  - 图片 → OCR 提取文字 → 情感分析 + 图片色彩倾向分析
"""
import io
import logging
import os
import sys
import uuid

# 确保脚本所在目录在 Python 搜索路径中（兼容中文路径）
_script_dir = os.path.dirname(os.path.abspath(__file__))
if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)

from flask import Flask, jsonify, render_template, request

import batch as batch_engine
import compliance
import crawler
import image_analyzer
import ocr_engine
import profile_store
import rule_miner
import seed_cases
import seed_marketing
import sentiment

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 单次请求最大 20MB

TEXT_EXT = {".txt", ".md", ".csv", ".log"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif"}
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")


# ---------------------------------------------------------------- 路由
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/analyze", methods=["POST"])
def analyze():
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    results = []

    # 1) 粘贴文本
    pasted = (request.form.get("text") or "").strip()
    if pasted:
        results.append(_analyze_text("粘贴文本", pasted))

    # 2) 上传文件
    for f in request.files.getlist("files"):
        if not f or not f.filename:
            continue
        name = f.filename
        ext = os.path.splitext(name)[1].lower()
        tmp_path = os.path.join(UPLOAD_DIR, uuid.uuid4().hex + ext)
        f.save(tmp_path)
        try:
            if ext in TEXT_EXT:
                results.append(_analyze_text(name, _read_text(tmp_path)))
            elif ext in IMAGE_EXT:
                results.append(_analyze_image(name, tmp_path))
            else:
                results.append({
                    "name": name,
                    "type": "unsupported",
                    "label": "不支持",
                    "error": "不支持的文件类型（仅支持文本 .txt/.md/.csv/.log 和图片）",
                })
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    if not results:
        return jsonify({"error": "没有可分析的内容，请粘贴文本或上传文件"}), 400

    negative_count = sum(1 for r in results
                         if r.get("type") != "unsupported" and r.get("label") == "负面")
    comp_cats = set()
    for r in results:
        for c in r.get("compliance") or []:
            comp_cats.add(c["category"])
    summary = {
        "total": len(results),
        "negative_count": negative_count,
        "has_negative": negative_count > 0,
        "compliance_count": len(comp_cats),
        "has_compliance": len(comp_cats) > 0,
        "compliance_categories": sorted(comp_cats),
    }
    return jsonify({"summary": summary, "results": results})


@app.route("/quick-capture", methods=["POST"])
def quick_capture():
    """截图分析专用路由：接收屏幕截图，返回可直接展示的 HTML 结果页。"""
    f = request.files.get("image")
    if not f or not f.filename:
        return "<h2>未收到截图，请重试</h2>", 400

    ext = os.path.splitext(f.filename)[1].lower()
    tmp_path = os.path.join(UPLOAD_DIR, uuid.uuid4().hex + (ext or ".png"))
    f.save(tmp_path)
    try:
        result = _analyze_image("屏幕截图", tmp_path)
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    # 构建结果 HTML
    label = result.get("label", "未知")
    risk = result.get("risk", 0)
    features = result.get("features") or []
    ocr_text = result.get("ocr_text", "")
    compliance = result.get("compliance") or []
    suggestions = result.get("suggestions") or []
    image_tendency = result.get("image_tendency") or {}

    # 风险颜色
    if label == "负面":
        label_color = "#D03B3B"
    elif label == "正面":
        label_color = "#199E70"
    else:
        label_color = "#8A94A6"

    # 合规行
    comp_rows = ""
    for c in compliance:
        sev = c.get("severity", "")
        sev_color = {"高": "#D03B3B", "中": "#E8A040", "低": "#8A94A6"}.get(sev, "#4A5568")
        comp_rows += (
            f'<tr><td style="color:{sev_color};font-weight:bold">{sev}风险</td>'
            f'<td>{c.get("category","")}</td>'
            f'<td>{c.get("keyword","")}</td></tr>'
        )

    # 建议行
    sug_rows = ""
    for s in suggestions:
        sug_rows += f'<tr><td>{s.get("category","")}</td><td>{s.get("suggestion","")}</td></tr>'

    # 特征词
    feat_tags = ""
    for fw in features:
        feat_tags += (
            f'<span style="display:inline-block;background:#EEF2FF;color:#2C4A75;'
            f'padding:3px 10px;border-radius:12px;margin:3px;font-size:13px">{fw}</span>'
        )

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>截图分析结果 · 云鉴</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:"Microsoft YaHei","微软雅黑",sans-serif;background:#F7F9FC;padding:24px;max-width:680px;margin:0 auto}}
.card{{background:#fff;border-radius:12px;padding:20px 24px;margin-bottom:14px;box-shadow:0 1px 4px rgba(0,0,0,.06)}}
.label{{display:inline-block;padding:6px 18px;border-radius:16px;font-size:20px;font-weight:bold;color:#fff;background:{label_color}}}
.risk-bar{{height:8px;border-radius:4px;background:#E2E8F0;margin-top:12px}}
.risk-fill{{height:8px;border-radius:4px;background:{label_color};width:{risk}%}}
.ocr-box{{background:#F7F9FC;border-radius:8px;padding:12px 16px;font-size:14px;color:#4A5568;max-height:120px;overflow-y:auto;white-space:pre-wrap}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{text-align:left;padding:8px 10px;border-bottom:2px solid #DDE3EC;color:#1A2233;font-weight:bold}}
td{{padding:8px 10px;border-bottom:1px solid #F0F2F5;color:#4A5568}}
h2{{font-size:16px;color:#1A2233;margin-bottom:12px}}
h3{{font-size:14px;color:#8A94A6;margin-bottom:4px;font-weight:normal}}
.footer{{text-align:center;color:#B0B8C8;font-size:12px;margin-top:20px}}
</style></head>
<body>
<div class="card">
  <h3>情感判定</h3>
  <span class="label">{label}</span>
  <div style="margin-top:8px;display:flex;align-items:center;gap:10px">
    <span style="font-size:14px;color:#4A5568">负面风险</span>
    <span style="font-size:22px;font-weight:bold;color:{label_color}">{risk}</span>
    <span style="font-size:14px;color:#8A94A6">/ 100</span>
  </div>
  <div class="risk-bar"><div class="risk-fill"></div></div>
</div>
"""
    if ocr_text:
        html += f'<div class="card"><h2>识别文字</h2><div class="ocr-box">{ocr_text}</div></div>'

    if feat_tags:
        html += f'<div class="card"><h2>特征词</h2><div>{feat_tags}</div></div>'

    if compliance:
        html += f"""<div class="card"><h2>合规风险</h2>
<table><tr><th>等级</th><th>类别</th><th>命中词</th></tr>{comp_rows}</table></div>"""

    if suggestions:
        html += f"""<div class="card"><h2>整改建议</h2>
<table><tr><th>类别</th><th>建议</th></tr>{sug_rows}</table></div>"""

    if image_tendency:
        html += f"""<div class="card"><h2>画面特征</h2>
<span style="font-size:14px;color:#4A5568">亮度 {image_tendency.get('brightness','?')} · 饱和度 {image_tendency.get('saturation','?')} · 压抑指数 {image_tendency.get('depression_index','?')}/100 · {image_tendency.get('description','')}</span></div>"""

    html += '<div class="footer">云鉴 · 员工言论合规分析 Agent · 截图分析</div></body></html>'
    return html


@app.route("/batch", methods=["POST"])
def batch_analyze():
    """批量分析：上传 CSV/XLSX 言论表（或 demo=1 用演示数据），返回统计看板。"""
    # 演示模式：直接读取演示 CSV
    if request.form.get("demo") == "1":
        demo = os.path.join(BASE_DIR, "demo_batch.csv")
        if not os.path.exists(demo):
            return jsonify({"error": "演示数据不存在，请先运行 make_demo_batch.py"}), 400
        try:
            table = batch_engine.read_table(demo)
            items = batch_engine.parse_rows(table)
            analyzed = batch_engine.analyze_batch(items)
            return jsonify(_attach_profiles(batch_engine.aggregate(analyzed), analyzed))
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "请上传 CSV 或 XLSX 文件"}), 400
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in {".csv", ".xlsx", ".xlsm"}:
        return jsonify({"error": "仅支持 .csv / .xlsx 文件"}), 400

    tmp_path = os.path.join(UPLOAD_DIR, uuid.uuid4().hex + ext)
    f.save(tmp_path)
    try:
        table = batch_engine.read_table(tmp_path)
        items = batch_engine.parse_rows(table)
        if not items:
            return jsonify({"error": "未解析到有效的言论数据（请确认首列是言论文本）"}), 400
        analyzed = batch_engine.analyze_batch(items)
        stats = _attach_profiles(batch_engine.aggregate(analyzed), analyzed)
        return jsonify(stats)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


# ---------------------------------------------------------------- 数据采集
@app.route("/collect", methods=["POST"])
def collect():
    """触发数据采集：处罚案例 + 银行产品宣传文本，实时优先，失败降级种子库。"""
    try:
        # 1) 处罚案例
        result = crawler.collect_cases()
        live = result["cases"]
        seed = seed_cases.load_cases()
        merged = crawler.merge_with_seed(live, seed)
        crawler.save_case_store(merged)

        # 2) 银行产品宣传文本
        mkt = crawler.collect_marketing()
        m_seed = seed_marketing.load_marketing()
        merged_m = crawler.merge_marketing_with_seed(mkt["samples"], m_seed)
        crawler.save_marketing_store(merged_m)

        notes = []
        if result["source"] == "live":
            notes.append("处罚案例实时采集")
        if mkt["source"] == "live":
            notes.append("宣传文本实时采集")
        if not notes:
            notes.append(result["note"])
            notes.append(mkt["note"])
        return jsonify({
            "source": result["source"],
            "total": len(merged),
            "marketing_count": len(merged_m),
            "live_count": len(live),
            "note": "；".join(notes),
        })
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": "采集失败：%s" % e}), 500


@app.route("/cases", methods=["GET"])
def list_cases():
    """案例库列表（支持 ?q= 关键词搜索）。"""
    q = (request.args.get("q") or "").strip()
    cases = crawler.load_case_store()
    if q:
        ql = q.lower()
        cases = [c for c in cases if any(
            ql in str(c.get(k, "")).lower() for k in ("violation", "org", "region", "type", "decision")
        )]
    return jsonify({"total": len(cases), "query": q, "cases": cases})


@app.route("/mine", methods=["GET"])
def mine_keywords():
    """从处罚案例 + 银行产品宣传文本提炼候选合规关键词。"""
    cases = crawler.load_case_store()
    results = rule_miner.mine(cases)
    marketing = crawler.load_marketing_store()
    results += rule_miner.mine_marketing(marketing)
    results = rule_miner.merge_groups(results)
    return jsonify({"total_cases": len(cases),
                    "marketing_count": len(marketing),
                    "groups": results})


@app.route("/profiles", methods=["GET"])
def get_profiles():
    """查看员工风险档案（跨批次累计，用于持续监测）。"""
    data = profile_store.load_profiles()
    _, ranked = profile_store.ranked(20)
    return jsonify({
        "sessions": data["sessions"],
        "updated_at": data["updated_at"],
        "employees": ranked,
    })


@app.route("/profiles/reset", methods=["POST"])
def reset_profiles():
    """清空全部员工风险档案。"""
    profile_store.reset_profiles()
    return jsonify({"ok": True})


@app.route("/apply", methods=["POST"])
def apply_keywords():
    """把候选关键词应用（并入）到运行时自定义词库 compliance_custom.py。"""
    data = request.get_json(silent=True) or {}
    category = (data.get("category") or "").strip()
    words = data.get("words") or []
    words = [str(w).strip() for w in words if str(w).strip()]

    if not category or not words:
        return jsonify({"error": "需要 category 和 words"}), 400

    path = os.path.join(BASE_DIR, "compliance_custom.py")
    try:
        ns = {}
        with open(path, "r", encoding="utf-8") as fh:
            exec(compile(fh.read(), path, "exec"), ns)
        custom = ns.get("CUSTOM_KEYWORDS", {}) or {}
    except (OSError, SyntaxError):
        custom = {}

    existing = set(custom.get(category, []))
    added = [w for w in words if w not in existing]
    custom[category] = list(dict.fromkeys(custom.get(category, []) + added))

    content = ('# -*- coding: utf-8 -*-\n'
               '"""\n运行时自定义合规词库（可选）\n'
               '============================\n'
               '由「词库提炼 → 应用候选词」功能自动维护，也可手动编辑。\n'
               '格式：CUSTOM_KEYWORDS = { "风险类别": ["词1", "词2"] }\n'
               '类别与内置 compliance_rules.py 同名时合并关键词；新类别默认"中"风险。\n'
               '"""\nCUSTOM_KEYWORDS = ' + repr(custom) + "\n")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)

    return jsonify({"category": category, "added": added,
                    "existing": list(custom[category])})


# ---------------------------------------------------------------- 分析辅助
def _attach_profiles(stats, analyzed):
    """把本批分析结果累计进员工风险档案，并把档案附到看板返回给前端。"""
    from datetime import date
    data = profile_store.update_from_items(analyzed, date.today().isoformat())
    _, ranked = profile_store.ranked(12)
    stats["has_name"] = any((x.get("name") or "").strip() for x in analyzed)
    stats["profiles"] = ranked
    stats["profile_sessions"] = data["sessions"]
    stats["profile_updated"] = data["updated_at"]
    return stats


def _analyze_text(name, content):
    content = (content or "").strip()
    res = sentiment.analyze(content)
    return {
        "name": name,
        "type": "text",
        "label": res["label"],
        "negative_risk": res["negative_risk"],
        "pos_score": res["pos_score"],
        "neg_score": res["neg_score"],
        "matched": res["matched"],
        "compliance": compliance.detect(content),
        "preview": content[:200],
    }


def _analyze_image(name, path):
    ocr_text, ocr_note = ocr_engine.recognize(path)
    mood = image_analyzer.analyze(path)

    result = {
        "name": name,
        "type": "image",
        "ocr_text": ocr_text,
        "ocr_note": ocr_note,
        "mood": mood,
    }
    if ocr_text:
        res = sentiment.analyze(ocr_text)
        result.update({
            "label": res["label"],
            "negative_risk": res["negative_risk"],
            "pos_score": res["pos_score"],
            "neg_score": res["neg_score"],
            "matched": res["matched"],
            "compliance": compliance.detect(ocr_text),
        })
    else:
        result.update({"label": "无文字", "negative_risk": None,
                       "matched": [], "compliance": []})
    return result


def _read_text(path):
    """尝试多种中文编码读取文本文件。"""
    for enc in ("utf-8", "gbk", "gb18030"):
        try:
            with io.open(path, "r", encoding=enc) as fh:
                return fh.read()
        except (UnicodeDecodeError, OSError):
            continue
    with io.open(path, "r", encoding="utf-8", errors="ignore") as fh:
        return fh.read()


if __name__ == "__main__":
    print("员工信息负面检测已启动：http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=False)
