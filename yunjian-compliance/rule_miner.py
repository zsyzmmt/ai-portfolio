# -*- coding: utf-8 -*-
"""
合规词库提炼器
==============
从处罚案例文本（seed 或爬取的实时案例）中提炼候选关键词，
供用户确认后并入运行时自定义词库（compliance_custom.py）。

提炼方法：
  1) 按案例 type 归入合规类别；
  2) 用每类的"语义种子词"在违规文本中抽取【含种子词】的 2~6 字短语；
     约束"必须含种子词"可滤掉大量与合规无关的通用词；
  3) 跨案例出现 ≥2 次的候选权重更高。

输出（每类）：
  {category, count, candidates: [{word, count}]}
"""
import re
from collections import Counter

# 每类合规风险的语义种子词（聚焦提取，避免提炼出无关通用词）
CAT_SEED = {
    "违规承诺收益": ["保本", "收益", "稳赚", "回报", "承诺", "刚性兑付", "分红", "保息"],
    "私售/飞单": ["飞单", "私售", "第三方", "非本行", "提成", "兜售", "代销", "私募", "私下销售"],
    "客户信息泄露": ["客户信息", "个人信息", "名单", "泄露", "出售", "共享", "导出", "私自查询"],
    "红线操作（代客/共享）": ["代客", "密码", "操作账户", "代操作", "共享账户", "代为", "代办", "代保管"],
    "洗钱/套现风险": ["套现", "洗钱", "虚构交易", "拆分交易", "走账", "可疑交易", "虚假商户"],
    "私下返佣/送礼": ["返佣", "回扣", "红包", "礼品", "送礼", "返利", "补贴", "提成"],
    "夸大/绝对化宣传": ["最高", "第一", "最优", "绝对", "稳赚不赔", "保底", "无风险", "夸大"],
    "情绪/服务负面": ["态度", "投诉", "辱骂", "拖延", "敷衍", "怠慢"],
}

# 停用词 / 通用词
STOPWORDS = {"银行", "客户", "监管", "规定", "相关", "部门", "机构", "网点", "支行",
             "人员", "员工", "该行", "被", "未", "及", "并", "等", "进行", "存在",
             "通过", "发生", "工作", "业务", "管理", "违反", "责令", "整改", "责任",
             "违规", "行为", "以及", "或者", "给予", "处以", "处罚", "决定", "处理",
             "处罚决定", "其中", "同时", "对于", "导致", "造成", "可能", "该", "其",
             "之", "中", "向", "在", "把", "将", "从", "为", "与", "和", "或"}

# 边界字：出现在词首/词尾通常表示截断
BAD_START = "向对把将由于被在从中为与之及和或从按当"
BAD_END = "的着了与及和或在从中为之们到过等而把将向对由于被从为并及和或其之也还就都于"

SPLIT_RE = re.compile(r"[。；;，,：:\n\s]+")


def _valid(word):
    """候选词有效性：长度、字集合、非停用词、边界字。"""
    if not (2 <= len(word) <= 6):
        return False
    if not re.fullmatch(r"[一-龥A-Za-z0-9]{2,}", word):
        return False
    if word in STOPWORDS:
        return False
    if word[0] in BAD_START or word[-1] in BAD_END:
        return False
    if any(w in word for w in STOPWORDS if len(w) == 2 and w not in ("违规",)):
        return False
    return True


def _extract_phrases(sentence, seeds):
    """从一句中提取所有"含任一种子词"的 2~6 字短语。"""
    phrases = []
    for seed in seeds:
        if seed not in sentence:
            continue
        pos = 0
        while True:
            i = sentence.find(seed, pos)
            if i == -1:
                break
            # 以 seed 为中心的 2~6 字窗口
            for n in range(2, 7):
                for j in range(max(0, i - 2), min(i + 1, len(sentence) - n + 1)):
                    sub = sentence[j:j + n]
                    if seed in sub and re.fullmatch(r"[一-龥A-Za-z0-9]+", sub):
                        phrases.append(sub)
            pos = i + 1
    return phrases


def _existing_words():
    """内置合规词库中的全部关键词（候选词若已存在则不再提炼）。"""
    existing = set()
    from compliance_rules import COMPLIANCE_RULES
    for rule in COMPLIANCE_RULES.values():
        existing.update(rule["keywords"])
    return existing


def _mine_texts(texts, seeds, existing):
    """对一组文本提炼候选关键词（含种子词 + 边界过滤 + 词频排序）。"""
    counter = Counter()
    for t in texts:
        for sent in SPLIT_RE.split(t):
            for ph in _extract_phrases(sent, seeds):
                if _valid(ph):
                    counter[ph] += 1
    # 已通过"含种子词 + 边界过滤"的候选，保留出现 ≥1 次的供用户挑选
    # （严格词频过滤会漏掉只在单个案例出现但有价值的词，如"刚性兑付"）
    candidates = [{"word": w, "count": n} for w, n in counter.items()
                  if w not in existing]
    candidates.sort(key=lambda x: (-x["count"], len(x["word"])))
    return candidates[:15]


def mine(cases):
    """从处罚案例列表提炼候选关键词。

    返回 [ {category, count, candidates:[{word,count}]} ]
    """
    by_cat = {}
    for c in cases:
        cat = c.get("type") or ""
        if not cat:
            continue
        by_cat.setdefault(cat, []).append(c.get("violation", ""))

    existing = _existing_words()
    results = []
    for cat, texts in by_cat.items():
        candidates = _mine_texts(texts, CAT_SEED.get(cat, []), existing)
        if candidates:
            results.append({"category": cat, "count": len(texts),
                            "candidates": candidates})
    return results


def mine_marketing(samples, category="夸大/绝对化宣传"):
    """从银行产品宣传文本提炼候选关键词（归入夸大/绝对化宣传类）。

    返回与 mine() 相同的结构；无候选时返回 []。
    """
    texts = [s.get("text", "") for s in samples if s.get("text")]
    if not texts:
        return []
    existing = _existing_words()
    candidates = _mine_texts(texts, CAT_SEED.get(category, []), existing)
    if candidates:
        return [{"category": category, "count": len(texts),
                 "candidates": candidates}]
    return []


def merge_groups(groups):
    """合并同类别的提炼结果（处罚案例与宣传语料可能归入同一类别）。

    同类别：count 相加，候选词按词去重、频次相加。
    """
    merged = {}
    for g in groups:
        cat = g.get("category", "")
        if cat not in merged:
            merged[cat] = {"category": cat, "count": 0, "candidates": {}}
        merged[cat]["count"] += g.get("count", 0)
        for c in g.get("candidates", []):
            w = c.get("word", "")
            if w:
                merged[cat]["candidates"][w] = merged[cat]["candidates"].get(w, 0) + c.get("count", 0)
    results = []
    for cat, g in merged.items():
        cands = [{"word": w, "count": n}
                 for w, n in sorted(g["candidates"].items(),
                                    key=lambda x: (-x[1], len(x[0])))]
        results.append({"category": cat, "count": g["count"],
                        "candidates": cands[:15]})
    results.sort(key=lambda x: -x["count"])
    return results
