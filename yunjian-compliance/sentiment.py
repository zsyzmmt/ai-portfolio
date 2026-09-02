# -*- coding: utf-8 -*-
"""
中文情感分析引擎（关键词 + 否定 + 程度副词）
纯 Python 实现，零第三方依赖，离线秒出结果。
判断逻辑：
  1. 按标点切句
  2. 逐句扫描词库关键词（长词优先，避免重叠重复计数）
  3. 检查关键词前的否定词 → 翻转极性；程度副词 → 调整权重
  4. 汇总正/负得分，计算"负面风险"0~100 与标签
"""
import re

from keywords import (NEGATIVE_WORDS, POSITIVE_WORDS,
                      NEGATIONS, STRONG_ADVERBS, WEAK_ADVERBS)


def _split_sentences(text):
    """按中文标点/换行切句。"""
    text = re.sub(r"\s+", "", text)
    parts = re.split(r"[。！？；!?;\n]+", text)
    return [p for p in parts if p]


def _find_keywords(text, word_weight):
    """在 text 中查找关键词，返回 [(pos, kw, weight)]。
    长词优先匹配；已覆盖的字符位置不再计数，避免"消极"和"消极怠工"重复计分。
    """
    results = []
    covered = set()
    for kw, w in sorted(word_weight.items(), key=lambda kv: -len(kv[0])):
        start = 0
        while True:
            pos = text.find(kw, start)
            if pos == -1:
                break
            # 若该区间已被更长的词覆盖，则跳过
            if not any(pos <= c < pos + len(kw) for c in covered):
                results.append((pos, kw, w))
                covered.update(range(pos, pos + len(kw)))
            start = pos + 1
    return results


def _check_negation(text, pos):
    """关键词前 3 字窗口内是否有否定词。"""
    window = text[max(0, pos - 3):pos]
    return any(neg in window for neg in NEGATIONS)


def _check_adverb(text, pos):
    """关键词前 3 字窗口内是否有程度副词，返回权重系数。"""
    window = text[max(0, pos - 3):pos]
    if any(adv in window for adv in STRONG_ADVERBS):
        return 1.5
    if any(adv in window for adv in WEAK_ADVERBS):
        return 0.7
    return 1.0


def analyze(text):
    """分析一段文本的情感。

    返回 dict：
      label          负面 / 中性 / 正面
      negative_risk  负面风险 0~100
      pos_score      正面得分
      neg_score      负面得分
      matched        命中的关键词清单（判定依据）
      sentence_count 句子数
      text           原文
    """
    text = (text or "").strip()
    if not text:
        return _empty_result()

    pos_score = 0.0
    neg_score = 0.0
    matched = []

    for sent in _split_sentences(text):
        # 负面词
        for pos, kw, w in _find_keywords(sent, NEGATIVE_WORDS):
            neg = _check_negation(sent, pos)
            val = round(w * _check_adverb(sent, pos), 2)
            if neg:                      # 如"没有迟到"→ 弱化为正面
                pos_score += val * 0.8
                matched.append({"word": "否" + kw, "type": "negative(被否定)", "weight": val})
            else:
                neg_score += val
                matched.append({"word": kw, "type": "negative", "weight": val})
        # 正面词
        for pos, kw, w in _find_keywords(sent, POSITIVE_WORDS):
            neg = _check_negation(sent, pos)
            val = round(w * _check_adverb(sent, pos), 2)
            if neg:                      # 如"不积极"→ 负面
                neg_score += val * 0.8
                matched.append({"word": "否" + kw, "type": "positive(被否定)", "weight": val})
            else:
                pos_score += val
                matched.append({"word": kw, "type": "positive", "weight": val})

    pos_score = round(pos_score, 2)
    neg_score = round(neg_score, 2)
    total = pos_score + neg_score

    if total == 0:
        label = "中性"
        negative_risk = 20           # 无明显正负面信号，风险低
    else:
        neg_ratio = neg_score / total
        negative_risk = int(round(neg_ratio * 100))
        if neg_ratio >= 0.55:
            label = "负面"
        elif neg_ratio <= 0.40:
            label = "正面"
        else:
            label = "中性"

    return {
        "label": label,
        "negative_risk": negative_risk,
        "pos_score": pos_score,
        "neg_score": neg_score,
        "matched": matched,
        "sentence_count": len(_split_sentences(text)),
        "text": text,
    }


def _empty_result():
    return {
        "label": "中性",
        "negative_risk": 0,
        "pos_score": 0.0,
        "neg_score": 0.0,
        "matched": [],
        "sentence_count": 0,
        "text": "",
    }
