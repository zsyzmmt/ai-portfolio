#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简历审核器：生成后自动审核，包含三个维度
1. 相似度审核：是否照搬上一份简历，是否根据JD改进
2. 真实性审核：与知识库对比，是否编造
3. 符合度审核：是否符合岗位JD的能力和关键词
不通过则打回重做，最终生成审核报告
"""

import json
import os
import re
import hashlib
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any
from datetime import datetime

import numpy as np


class ResumeAuditor:
    """简历审核器"""

    def __init__(self, config: Dict, knowledge_base=None, llm_client=None):
        """
        Args:
            config: 完整配置字典
            knowledge_base: KnowledgeBase实例（用于真实性审核）
            llm_client: LLMClient实例（用于深度审核）
        """
        self.config = config
        self.kb = knowledge_base
        self.llm = llm_client

        audit_config = config.get("audit", {})
        self.history_dir = Path(audit_config.get("history_dir", "./output/history"))
        self.report_dir = Path(audit_config.get("report_dir", "./output/audit_reports"))
        self.similarity_threshold = audit_config.get("similarity_threshold", 0.80)
        self.truthfulness_threshold = audit_config.get("truthfulness_threshold", 0.60)
        self.compliance_threshold = audit_config.get("compliance_threshold", 0.60)
        self.max_history_compare = audit_config.get("max_history_compare", 5)
        self.auto_retry = audit_config.get("auto_retry", True)
        self.max_retries = audit_config.get("max_retries", 2)

        self.history_dir.mkdir(parents=True, exist_ok=True)
        self.report_dir.mkdir(parents=True, exist_ok=True)

    # ============================================================
    # 主审核流程
    # ============================================================
    def audit(self, resume_json: Dict, jd_text: str, company: str = "",
              position: str = "", auto_fix: bool = False) -> Dict:
        """
        审核简历

        Args:
            resume_json: 简历JSON
            jd_text: 岗位JD文本
            company: 公司名
            position: 岗位名
            auto_fix: 是否自动修复（打回重做）

        Returns:
            dict: 审核结果
        """
        print(f"\n{'='*60}")
        print(f"开始审核: {company} - {position}")
        print(f"{'='*60}")

        # 保存当前简历到历史
        self._save_to_history(resume_json, company, position)

        # 1. 相似度审核
        print("\n[1/4] 相似度审核...")
        similarity_result = self._audit_similarity(resume_json, company, position)

        # 2. 真实性审核
        print("\n[2/4] 真实性审核...")
        truthfulness_result = self._audit_truthfulness(resume_json)

        # 3. 符合度审核
        print("\n[3/4] 符合度审核...")
        compliance_result = self._audit_compliance(resume_json, jd_text)

        # 4. LLM深度审核
        print("\n[4/4] LLM深度审核...")
        llm_result = self._llm_audit(resume_json, jd_text, similarity_result,
                                       truthfulness_result, compliance_result)

        # 综合判断
        overall = self._compute_overall(similarity_result, truthfulness_result,
                                         compliance_result, llm_result)

        audit_result = {
            "company": company,
            "position": position,
            "audit_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "similarity": similarity_result,
            "truthfulness": truthfulness_result,
            "compliance": compliance_result,
            "llm_audit": llm_result,
            "overall": overall,
            "resume_hash": self._compute_resume_hash(resume_json)
        }

        # 打印审核摘要
        self._print_audit_summary(audit_result)

        # 自动修复
        if auto_fix and not overall["passed"] and self.auto_retry:
            print(f"\n审核未通过，自动打回重做（剩余{self.max_retries}次）...")
            # 这里返回需要重做的标记，由调用方决定是否重新生成
            audit_result["need_retry"] = True
            audit_result["retry_suggestions"] = overall["issues"]
        else:
            audit_result["need_retry"] = False

        return audit_result

    # ============================================================
    # 1. 相似度审核
    # ============================================================
    def _audit_similarity(self, resume_json: Dict, company: str,
                          position: str) -> Dict:
        """
        相似度审核：与历史简历对比，判断是否照搬

        Returns:
            dict: {score, max_similarity, most_similar_file, details, issues, passed}
        """
        # 加载历史简历
        history_files = self._load_history(company, position)

        if not history_files:
            return {
                "score": 100,
                "max_similarity": 0,
                "most_similar_file": None,
                "details": [],
                "issues": ["无历史简历可对比（首次生成）"],
                "passed": True,
                "note": "首次生成，无历史对比基准"
            }

        # 提取当前简历文本
        current_text = self._extract_resume_text(resume_json)
        current_points = self._extract_experience_points(resume_json)

        details = []
        max_similarity = 0
        most_similar_file = None
        all_issues = []

        for hist_file in history_files[:self.max_history_compare]:
            try:
                with open(hist_file, 'r', encoding='utf-8') as f:
                    hist_resume = json.load(f)
            except Exception:
                continue

            hist_text = self._extract_resume_text(hist_resume)
            hist_points = self._extract_experience_points(hist_resume)

            # 计算整体文本相似度
            overall_sim = self._text_similarity(current_text, hist_text)

            # 计算经历点级别的相似度
            point_similarities = []
            for i, curr_pt in enumerate(current_points):
                best_sim = 0
                best_hist_idx = -1
                for j, hist_pt in enumerate(hist_points):
                    sim = self._text_similarity(curr_pt, hist_pt)
                    if sim > best_sim:
                        best_sim = sim
                        best_hist_idx = j
                point_similarities.append({
                    "current_point_idx": i,
                    "current_point": curr_pt[:80],
                    "best_match_idx": best_hist_idx,
                    "best_match": hist_points[best_hist_idx][:80] if best_hist_idx >= 0 else "",
                    "similarity": round(best_sim, 4)
                })

            high_sim_points = [p for p in point_similarities if p["similarity"] > self.similarity_threshold]
            avg_point_sim = np.mean([p["similarity"] for p in point_similarities]) if point_similarities else 0

            details.append({
                "history_file": hist_file.name,
                "history_company": hist_resume.get("company", ""),
                "history_position": hist_resume.get("position", ""),
                "overall_similarity": round(overall_sim, 4),
                "avg_point_similarity": round(avg_point_sim, 4),
                "high_similarity_points": len(high_sim_points),
                "total_points": len(point_similarities),
                "point_details": point_similarities
            })

            if overall_sim > max_similarity:
                max_similarity = overall_sim
                most_similar_file = hist_file.name

            # 检查问题
            if overall_sim > self.similarity_threshold:
                all_issues.append(
                    f"与历史简历「{hist_resume.get('company', '')}-{hist_resume.get('position', '')}」"
                    f"整体相似度{overall_sim:.1%}，超过阈值{self.similarity_threshold:.0%}，疑似照搬"
                )
            if len(high_sim_points) > len(point_similarities) * 0.5 and len(point_similarities) > 0:
                all_issues.append(
                    f"与「{hist_resume.get('position', '')}」简历有{len(high_sim_points)}/{len(point_similarities)}"
                    f"个经历点高度相似（>{self.similarity_threshold:.0%}），未根据JD调整表述角度"
                )

        # 计算分数：相似度越低越好（说明做了针对性修改）
        # max_similarity=0 -> 100分, max_similarity=1 -> 0分
        score = max(0, int((1 - max_similarity) * 100))
        passed = max_similarity <= self.similarity_threshold

        return {
            "score": score,
            "max_similarity": round(max_similarity, 4),
            "most_similar_file": most_similar_file,
            "threshold": self.similarity_threshold,
            "details": details,
            "issues": all_issues,
            "passed": passed
        }

    # ============================================================
    # 2. 真实性审核
    # ============================================================
    def _audit_truthfulness(self, resume_json: Dict) -> Dict:
        """
        真实性审核：与知识库对比，判断是否编造

        Returns:
            dict: {score, details, issues, passed}
        """
        if not self.kb:
            return {
                "score": 100,
                "details": [],
                "issues": ["知识库未连接，跳过真实性审核"],
                "passed": True,
                "note": "无知识库，跳过真实性核验"
            }

        # 提取所有经历点
        all_points = []
        for intern in resume_json.get("internships", []):
            for pt in intern.get("points", []):
                all_points.append({
                    "type": "实习",
                    "org": intern.get("org", ""),
                    "role": intern.get("role", ""),
                    "kw": pt.get("kw", ""),
                    "text": pt.get("text", "")
                })
        for proj in resume_json.get("projects", []):
            for pt in proj.get("points", []):
                all_points.append({
                    "type": "项目",
                    "org": proj.get("org", ""),
                    "role": proj.get("role", ""),
                    "kw": pt.get("kw", ""),
                    "text": pt.get("text", "")
                })

        details = []
        all_issues = []
        total_score = 0

        for point in all_points:
            text = point["text"]
            if not text:
                continue

            # 从知识库检索最相关的素材
            query = f"{point['org']} {point['kw']} {text[:200]}"
            results = self.kb.search(query, top_k=5, score_threshold=0.0)

            # 计算与最相关素材的相似度（包含度：要点被知识库素材覆盖的比例）
            # 同时合并多条检索结果的n-gram，避免证据分散在不同chunk时被低估
            max_kb_sim = 0
            best_source = ""
            best_text = ""
            union_ngrams = set()
            for r in results:
                union_ngrams.update(self._ngrams(r["text"]))
                sim = self._text_containment(text, r["text"])
                if sim > max_kb_sim:
                    max_kb_sim = sim
                    best_source = r["source"]
                    best_text = r["text"][:200]
            if union_ngrams:
                union_sim = self._text_containment(text, "", preset_ngrams=union_ngrams)
                if union_sim > max_kb_sim:
                    max_kb_sim = union_sim
                    best_source = best_source or (results[0]["source"] if results else "")
                    if not best_text and results:
                        best_text = results[0]["text"][:200]

            # 提取量化数字，检查是否在知识库中出现
            numbers_in_resume = self._extract_numbers(text)
            numbers_in_kb = set()
            for r in results:
                numbers_in_kb.update(self._extract_numbers(r["text"]))

            # 判断数字是否有依据
            unsupported_numbers = []
            for num in numbers_in_resume:
                # 宽松匹配：数字的核心部分是否在知识库中出现
                num_core = re.sub(r'[^\d]', '', num)
                if len(num_core) >= 2:
                    found = any(num_core in re.sub(r'[^\d]', '', kb_num) for kb_num in numbers_in_kb)
                    if not found:
                        unsupported_numbers.append(num)

            # 真实性评分
            # 知识库包含度高 -> 有依据 -> 分数高
            # 无依据的数字多 -> 分数低
            # 包含度0.5以上视为满分（表述改写但仍可溯源）
            base_score = min(100.0, max_kb_sim * 200)
            penalty = len(unsupported_numbers) * 10
            point_score = max(0, min(100, int(base_score - penalty)))
            total_score += point_score

            is_suspicious = max_kb_sim < 0.05 or len(unsupported_numbers) >= 2

            detail = {
                "type": point["type"],
                "org": point["org"],
                "kw": point["kw"],
                "text_preview": text[:150],
                "kb_similarity": round(max_kb_sim, 4),
                "best_source": best_source,
                "best_kb_text": best_text,
                "numbers_in_resume": numbers_in_resume,
                "unsupported_numbers": unsupported_numbers,
                "score": point_score,
                "suspicious": is_suspicious
            }
            details.append(detail)

            if is_suspicious:
                issue = f"[{point['type']}] {point['org']} - {point['kw']}: "
                if max_kb_sim < 0.05:
                    issue += "知识库中未找到相关素材依据"
                if unsupported_numbers:
                    issue += f"，量化数字{', '.join(unsupported_numbers[:3])}无知识库支撑"
                all_issues.append(issue)

        avg_score = int(total_score / len(all_points)) if all_points else 100
        passed = avg_score >= self.truthfulness_threshold * 100 and len(all_issues) <= len(all_points) * 0.3

        return {
            "score": avg_score,
            "threshold": self.truthfulness_threshold,
            "total_points": len(all_points),
            "suspicious_points": len([d for d in details if d["suspicious"]]),
            "details": details,
            "issues": all_issues,
            "passed": passed
        }

    # ============================================================
    # 3. 符合度审核
    # ============================================================
    def _audit_compliance(self, resume_json: Dict, jd_text: str) -> Dict:
        """
        符合度审核：简历是否符合岗位JD的能力和关键词

        Returns:
            dict: {score, jd_keywords, matched_keywords, missing_keywords, details, issues, passed}
        """
        # 提取JD关键词
        jd_keywords = self._extract_jd_keywords(jd_text)
        all_keywords = jd_keywords["hard_skills"] + jd_keywords["soft_skills"]

        # 提取简历全文
        resume_text = self._extract_resume_text(resume_json).lower()

        # 匹配关键词
        matched = []
        missing = []
        for kw in all_keywords:
            if kw.lower() in resume_text:
                matched.append(kw)
            else:
                missing.append(kw)

        # 计算覆盖率
        coverage = len(matched) / len(all_keywords) if all_keywords else 0

        # 检查核心关键词（前10个硬技能+前5个软技能）
        core_keywords = jd_keywords["hard_skills"][:10] + jd_keywords["soft_skills"][:5]
        core_matched = [kw for kw in core_keywords if kw.lower() in resume_text]
        core_missing = [kw for kw in core_keywords if kw.lower() not in resume_text]
        core_coverage = len(core_matched) / len(core_keywords) if core_keywords else 0

        # 检查岗位匹配优势段落是否包含关键词
        summary = resume_json.get("summary", "").lower()
        summary_keywords = [kw for kw in all_keywords if kw.lower() in summary]

        # 评分：核心关键词覆盖率权重70%，整体覆盖率权重30%
        score = int(core_coverage * 70 + coverage * 30)

        issues = []
        if core_missing:
            issues.append(f"核心关键词缺失: {', '.join(core_missing[:8])}")
        if coverage < 0.5:
            issues.append(f"JD关键词整体覆盖率仅{coverage:.1%}，建议增加相关表述")
        if len(summary_keywords) < 3:
            issues.append("岗位匹配优势段落嵌入的JD关键词不足，建议密集嵌入核心关键词")

        passed = score >= self.compliance_threshold * 100

        return {
            "score": score,
            "threshold": self.compliance_threshold,
            "jd_keywords_count": len(all_keywords),
            "matched_count": len(matched),
            "missing_count": len(missing),
            "coverage": round(coverage, 4),
            "core_keywords": core_keywords,
            "core_matched": core_matched,
            "core_missing": core_missing,
            "core_coverage": round(core_coverage, 4),
            "summary_keywords": summary_keywords,
            "matched_keywords": matched,
            "missing_keywords": missing,
            "issues": issues,
            "passed": passed
        }

    # ============================================================
    # 4. LLM深度审核
    # ============================================================
    def _llm_audit(self, resume_json: Dict, jd_text: str,
                    similarity_result: Dict, truthfulness_result: Dict,
                    compliance_result: Dict) -> Dict:
        """LLM深度审核：综合判断，给出审核意见和修改建议"""

        if not self.llm:
            return {
                "score": 100,
                "verdict": "跳过（无LLM）",
                "summary": "LLM未配置，跳过深度审核",
                "suggestions": [],
                "passed": True
            }

        # 预检查：LLM是否有有效API密钥
        try:
            model_config = self.llm.model_config
            api_key = model_config.get("api_key", "")
            if not api_key or api_key.startswith("your-") or api_key.startswith("sk-xxxx"):
                return {
                    "score": 100,
                    "verdict": "跳过（API未配置）",
                    "summary": "LLM API密钥未配置，跳过深度审核（机器审核三维度已完成）",
                    "suggestions": [],
                    "passed": True
                }
        except Exception:
            pass

        # 构建审核提示词
        resume_summary = self._resume_to_text(resume_json)

        prompt = f"""你是一位严格的简历审核专家。请对以下简历进行深度审核，重点检查三个问题：

## 岗位JD
{jd_text[:1500]}

## 简历内容
{resume_summary}

## 机器初审结果
- 相似度审核：{similarity_result['score']}分（{'通过' if similarity_result['passed'] else '未通过'}）
  最大相似度：{similarity_result.get('max_similarity', 0):.1%}
  问题：{'; '.join(similarity_result.get('issues', [])[:3]) or '无'}

- 真实性审核：{truthfulness_result['score']}分（{'通过' if truthfulness_result['passed'] else '未通过'}）
  可疑经历点：{truthfulness_result.get('suspicious_points', 0)}/{truthfulness_result.get('total_points', 0)}
  问题：{'; '.join(truthfulness_result.get('issues', [])[:3]) or '无'}

- 符合度审核：{compliance_result['score']}分（{'通过' if compliance_result['passed'] else '未通过'}）
  核心关键词覆盖率：{compliance_result.get('core_coverage', 0):.1%}
  缺失核心关键词：{', '.join(compliance_result.get('core_missing', [])[:5]) or '无'}
  问题：{'; '.join(compliance_result.get('issues', [])[:3]) or '无'}

## 审核要求
1. 判断简历是否照搬上一份（表述角度是否根据JD做了调整）
2. 判断是否有编造迹象（量化数字、经历是否有依据）
3. 判断是否符合JD要求（核心能力和关键词是否覆盖）
4. 给出具体的修改建议（指出哪个经历点需要怎么改）

## 输出格式（JSON）
{{
  "score": 0-100的综合评分,
  "verdict": "通过" / "需修改" / "严重问题",
  "summary": "一句话审核结论",
  "similarity_comment": "对相似度的评价",
  "truthfulness_comment": "对真实性的评价",
  "compliance_comment": "对符合度的评价",
  "suggestions": ["具体修改建议1", "具体修改建议2", ...],
  "must_fix": ["必须修改的问题（不修改不能通过）", ...]
}}

只输出JSON，不要输出其他文字。"""

        try:
            response = self.llm.chat_with_retry([
                {"role": "system", "content": "你是一位严格的简历审核专家，只输出JSON。"},
                {"role": "user", "content": prompt}
            ])
            result = self.llm.extract_json(response)
            result["passed"] = result.get("score", 0) >= 60 and result.get("verdict", "") != "严重问题"
            return result
        except Exception as e:
            return {
                "score": 100,
                "verdict": "LLM审核失败",
                "summary": f"LLM审核出错: {e}",
                "suggestions": [],
                "passed": True
            }

    # ============================================================
    # 综合判断
    # ============================================================
    def _compute_overall(self, similarity: Dict, truthfulness: Dict,
                          compliance: Dict, llm: Dict) -> Dict:
        """综合三个维度+LLM审核，给出最终结论"""
        # 加权评分：相似度25% + 真实性35% + 符合度25% + LLM 15%
        weighted_score = (
            similarity.get("score", 100) * 0.25 +
            truthfulness.get("score", 100) * 0.35 +
            compliance.get("score", 100) * 0.25 +
            llm.get("score", 100) * 0.15
        )

        all_issues = []
        all_issues.extend(similarity.get("issues", []))
        all_issues.extend(truthfulness.get("issues", []))
        all_issues.extend(compliance.get("issues", []))
        all_issues.extend(llm.get("must_fix", []))

        # 任一维度严重不通过则整体不通过
        dimension_passed = (
            similarity.get("passed", True) and
            truthfulness.get("passed", True) and
            compliance.get("passed", True) and
            llm.get("passed", True)
        )

        passed = dimension_passed and weighted_score >= 60

        if passed:
            verdict = "通过"
        elif weighted_score >= 40:
            verdict = "需修改"
        else:
            verdict = "严重问题，建议重做"

        return {
            "weighted_score": int(weighted_score),
            "verdict": verdict,
            "passed": passed,
            "issues": all_issues,
            "dimension_scores": {
                "similarity": similarity.get("score", 100),
                "truthfulness": truthfulness.get("score", 100),
                "compliance": compliance.get("score", 100),
                "llm": llm.get("score", 100)
            }
        }

    # ============================================================
    # 历史简历管理
    # ============================================================
    def _save_to_history(self, resume_json: Dict, company: str, position: str):
        """保存简历到历史记录"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_company = re.sub(r'[\\/:*?"<>|]', '_', company)
        safe_position = re.sub(r'[\\/:*?"<>|]', '_', position)
        filename = f"{timestamp}_{safe_company}_{safe_position}.json"
        filepath = self.history_dir / filename

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(resume_json, f, ensure_ascii=False, indent=2)

    def _load_history(self, exclude_company: str = "",
                      exclude_position: str = "") -> List[Path]:
        """加载历史简历（按时间倒序，排除当前公司岗位）"""
        if not self.history_dir.exists():
            return []

        files = sorted(self.history_dir.glob("*.json"), reverse=True)
        result = []
        for f in files:
            try:
                with open(f, 'r', encoding='utf-8') as fp:
                    data = json.load(fp)
                # 排除同公司同岗位的（避免自己和自己比）
                if (data.get("company") == exclude_company and
                        data.get("position") == exclude_position):
                    continue
                result.append(f)
            except Exception:
                continue
        return result

    # ============================================================
    # 工具方法
    # ============================================================
    @staticmethod
    def _extract_resume_text(resume_json: Dict) -> str:
        """提取简历全文本"""
        parts = [resume_json.get("summary", "")]
        for intern in resume_json.get("internships", []):
            parts.append(intern.get("org", ""))
            parts.append(intern.get("role", ""))
            for p in intern.get("points", []):
                parts.append(p.get("kw", ""))
                parts.append(p.get("text", ""))
        for proj in resume_json.get("projects", []):
            parts.append(proj.get("org", ""))
            parts.append(proj.get("role", ""))
            for p in proj.get("points", []):
                parts.append(p.get("kw", ""))
                parts.append(p.get("text", ""))
        for adv in resume_json.get("advantages", []):
            parts.append(adv)
        return " ".join(parts)

    @staticmethod
    def _extract_experience_points(resume_json: Dict) -> List[str]:
        """提取所有经历点文本"""
        points = []
        for intern in resume_json.get("internships", []):
            for p in intern.get("points", []):
                points.append(f"{p.get('kw', '')} {p.get('text', '')}")
        for proj in resume_json.get("projects", []):
            for p in proj.get("points", []):
                points.append(f"{p.get('kw', '')} {p.get('text', '')}")
        return points

    @staticmethod
    def _text_similarity(text1: str, text2: str) -> float:
        """计算两段文本的相似度（基于字符n-gram的Jaccard相似度）"""
        if not text1 or not text2:
            return 0.0

        def get_ngrams(text, n=3):
            text = text.lower()
            return set(text[i:i+n] for i in range(len(text) - n + 1))

        ngrams1 = get_ngrams(text1)
        ngrams2 = get_ngrams(text2)

        if not ngrams1 or not ngrams2:
            return 0.0

        intersection = ngrams1 & ngrams2
        union = ngrams1 | ngrams2
        return len(intersection) / len(union) if union else 0.0

    @staticmethod
    def _ngrams(text: str, n: int = 3):
        """生成字符n-gram列表"""
        text = text.lower()
        return [text[i:i+n] for i in range(len(text) - n + 1)]

    @staticmethod
    def _text_containment(text: str, source: str, preset_ngrams: set = None) -> float:
        """计算短文本被长文本覆盖的程度（基于字符3-gram包含度）

        与Jaccard不同，包含度 = 交集 / 短文本n-gram数，
        用于判断"简历要点是否能在知识库素材中找到依据"，
        不受两段文本长度悬殊的影响。
        preset_ngrams: 可传入预先合并的n-gram集合，覆盖多段素材。
        """
        if not text:
            return 0.0

        ngrams1 = ResumeAuditor._ngrams(text)
        if not ngrams1:
            return 0.0

        if preset_ngrams is not None:
            ngrams2 = preset_ngrams
        else:
            if not source:
                return 0.0
            ngrams2 = set(ResumeAuditor._ngrams(source))
        if not ngrams2:
            return 0.0

        covered = sum(1 for g in ngrams1 if g in ngrams2)
        return covered / len(ngrams1)

    @staticmethod
    def _extract_numbers(text: str) -> List[str]:
        """提取文本中的量化数字（含单位）"""
        # 匹配数字+单位的组合
        patterns = [
            r'\d+(?:\.\d+)?%',           # 百分比
            r'\d+(?:\.\d+)?万',           # 万
            r'\d+(?:\.\d+)?亿',           # 亿
            r'\d+(?:\.\d+)?家',           # 家
            r'\d+(?:\.\d+)?份',           # 份
            r'\d+(?:\.\d+)?人',           # 人
            r'\d+(?:\.\d+)?个',           # 个
            r'\d+(?:\.\d+)?项',           # 项
            r'\d+(?:\.\d+)?条',           # 条
            r'\d+(?:\.\d+)?元',           # 元
            r'\d+(?:\.\d+)?天',           # 天
            r'\d+(?:\.\d+)?月',           # 月
            r'\d+(?:\.\d+)?年',           # 年
            r'\d+(?:\.\d+)?倍',           # 倍
            r'\d+(?:\.\d+)?页',           # 页
            r'\d+(?:\.\d+)?篇',           # 篇
            r'\d+(?:\.\d+)?次',           # 次
            r'\d+(?:\.\d+)?名',           # 名
            r'\d+(?:\.\d+)?户',           # 户
            r'\d+(?:\.\d+)?笔',           # 笔
            r'\d+(?:\.\d+)?单',           # 单
            r'\d+(?:\.\d+)?\$',           # 美元
            r'\$\d+(?:\.\d+)?',           # $数字
        ]
        numbers = []
        for pattern in patterns:
            numbers.extend(re.findall(pattern, text))
        # 去重
        return list(set(numbers))

    @staticmethod
    def _extract_jd_keywords(jd_text: str) -> Dict:
        """从JD提取关键词（与generator中保持一致）"""
        keywords = {"hard_skills": [], "soft_skills": [], "requirements": [], "bonus": []}

        hard_skills = [
            "数据分析", "Excel", "Python", "SQL", "PPT", "Word", "Office",
            "SPSS", "财务建模", "统计分析", "数据可视化", "机器学习", "AI",
            "市场调研", "问卷设计", "用户研究", "产品运营", "内容运营",
            "活动策划", "营销策划", "渠道运营", "用户增长", "项目管理",
            "流程优化", "需求分析", "产品设计", "Tableau", "Power BI",
            "Eviews", "Stata", "R语言", "飞书", "钉钉", "企业微信",
            "协同办公", "自动化", "数据挖掘", "NLP", "大模型", "LLM",
            "财务分析", "风险控制", "信贷", "投资", "估值", "建模",
            "用户画像", "A/B测试", "漏斗分析", "留存分析", "转化分析",
            "社群运营", "私域运营", "直播运营", "电商运营", "新媒体运营",
            "文案", "编辑", "视频剪辑", "PR", "AE", "PS", "设计",
            "游戏策划", "数值策划", "系统策划", "VOC", "NPS", "CES", "CSAT",
            "体验运营", "用户体验", "满意度", "台账", "报表", "会议纪要",
            "文档撰写", "工作总结", "汇报材料", "演示文稿", "预算", "绩效",
            "销售", "商务", "客户", "运营", "策划", "推广", "品牌",
            "供应链", "采购", "物流", "仓储", "库存", "订单", "客服",
            "培训", "招聘", "人力资源", "绩效", "薪酬", "员工关系",
            "审计", "合规", "法务", "税务", "会计", "出纳", "成本",
            "研发", "测试", "运维", "前端", "后端", "算法", "架构",
            "游戏", "电竞", "直播", "短视频", "内容", "社区", "社交",
            "教育", "培训", "课程", "教研", "教学", "学习", "知识",
            "医疗", "健康", "康养", "养老", "护理", "康复", "心理咨询",
            "金融", "银行", "证券", "保险", "基金", "期货", "外汇",
            "快消", "零售", "商超", "便利店", "餐饮", "酒店", "旅游",
            "汽车", "房产", "家居", "家电", "3C", "数码", "服装",
            "美妆", "母婴", "食品", "饮料", "酒水", "烟草", "茶叶",
        ]

        soft_skills = [
            "沟通协调", "跨部门", "团队合作", "团队管理", "统筹", "规划",
            "组织能力", "执行力", "抗压", "学习能力", "适应能力",
            "逻辑思维", "分析能力", "解决问题", "创新", "文案撰写",
            "文档撰写", "会议纪要", "汇报", "演讲", "谈判", "客户服务",
            "商务拓展", "时间管理", "多任务", "细致", "严谨", "责任心",
            "保密", "职业素养", "文字功底", "表达能力", "人际交往",
            "资源整合", "推动", "落地", "闭环", "复盘", "迭代",
            "主动", "积极", "稳重", "踏实", "可靠", "敏锐", "洞察",
            "沟通", "协作", "协调", "统筹规划", "领导力", "决策力",
            "影响力", "说服力", "亲和力", "服务意识", "客户导向",
            "结果导向", "目标导向", "数据驱动", "用户导向", "产品思维",
            "商业思维", "战略思维", "全局观", "前瞻性", "判断力",
        ]

        requirements = [
            "本科", "硕士", "博士", "985", "211", "双一流", "应届",
            "实习生", "1年", "2年", "3年", "5年", "经验", "持证",
            "证书", "英语", "CET-4", "CET-6", "雅思", "托福", "驾照",
            "普通话", "党员", "学生干部", "奖学金",
        ]

        jd_lower = jd_text.lower()
        for word in hard_skills:
            if word.lower() in jd_lower and word not in keywords["hard_skills"]:
                keywords["hard_skills"].append(word)
        for word in soft_skills:
            if word.lower() in jd_lower and word not in keywords["soft_skills"]:
                keywords["soft_skills"].append(word)
        for word in requirements:
            if word.lower() in jd_lower and word not in keywords["requirements"]:
                keywords["requirements"].append(word)

        return keywords

    @staticmethod
    def _resume_to_text(resume_json: Dict) -> str:
        """将简历JSON转为可读文本（用于LLM审核）"""
        lines = []
        lines.append(f"姓名: {resume_json.get('name', '')}")
        lines.append(f"岗位匹配优势: {resume_json.get('summary', '')}")
        lines.append("")
        lines.append("【实习经历】")
        for intern in resume_json.get("internships", []):
            lines.append(f"  {intern.get('org', '')} | {intern.get('role', '')} | {intern.get('time', '')}")
            for p in intern.get("points", []):
                lines.append(f"    - [{p.get('kw', '')}] {p.get('text', '')}")
        lines.append("")
        lines.append("【项目经历】")
        for proj in resume_json.get("projects", []):
            lines.append(f"  {proj.get('org', '')} | {proj.get('role', '')} | {proj.get('time', '')}")
            for p in proj.get("points", []):
                lines.append(f"    - [{p.get('kw', '')}] {p.get('text', '')}")
        lines.append("")
        lines.append("【个人优势】")
        for adv in resume_json.get("advantages", []):
            lines.append(f"  - {adv}")
        return "\n".join(lines)

    @staticmethod
    def _compute_resume_hash(resume_json: Dict) -> str:
        """计算简历内容哈希"""
        content = json.dumps(resume_json, sort_keys=True, ensure_ascii=False)
        return hashlib.md5(content.encode('utf-8')).hexdigest()[:12]

    @staticmethod
    def _print_audit_summary(result: Dict):
        """打印审核摘要"""
        overall = result["overall"]
        print(f"\n{'='*60}")
        print(f"审核结果: {overall['verdict']} (综合评分: {overall['weighted_score']}/100)")
        print(f"{'='*60}")
        print(f"  相似度审核: {result['similarity']['score']}/100 {'✓' if result['similarity']['passed'] else '✗'}")
        print(f"  真实性审核: {result['truthfulness']['score']}/100 {'✓' if result['truthfulness']['passed'] else '✗'}")
        print(f"  符合度审核: {result['compliance']['score']}/100 {'✓' if result['compliance']['passed'] else '✗'}")
        print(f"  LLM深度审核: {result['llm_audit']['score']}/100 {'✓' if result['llm_audit'].get('passed', True) else '✗'}")
        if overall["issues"]:
            print(f"\n  发现 {len(overall['issues'])} 个问题:")
            for i, issue in enumerate(overall["issues"][:10], 1):
                print(f"    {i}. {issue}")
        if result["llm_audit"].get("suggestions"):
            print(f"\n  修改建议:")
            for i, sug in enumerate(result["llm_audit"]["suggestions"][:5], 1):
                print(f"    {i}. {sug}")
