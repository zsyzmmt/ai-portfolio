#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简历Agent：自主循环生成+审核，直到通过
这是resume-kit从"工具链"升级为"agent"的核心模块
循环逻辑：生成 → 审核 → 不通过 → LLM根据审核意见修改 → 重新生成 → 重新审核 → 直到通过或达最大重试
"""

import json
import re
import copy
from pathlib import Path
from typing import Dict, Optional, List, Any
from datetime import datetime

from .generator import ResumeGenerator
from .auditor import ResumeAuditor


class ResumeAgent:
    """
    简历Agent：自主循环生成+审核
    具备agent的核心特征：感知（审核结果）→ 决策（是否通过）→ 行动（修改简历）→ 循环（直到达标）
    """

    def __init__(self, config: Dict, knowledge_base=None, llm_client=None):
        """
        Args:
            config: 完整配置字典
            knowledge_base: KnowledgeBase实例
            llm_client: LLMClient实例
        """
        self.config = config
        self.kb = knowledge_base
        self.llm = llm_client

        self.generator = ResumeGenerator(config, knowledge_base=knowledge_base, llm_client=llm_client)
        self.auditor = ResumeAuditor(config, knowledge_base=knowledge_base, llm_client=llm_client)

        agent_config = config.get("agent", {})
        self.max_retries = agent_config.get("max_retries", 3)
        self.target_score = agent_config.get("target_score", 70)
        self.auto_save = agent_config.get("auto_save", True)
        self.output_dir = Path(agent_config.get("output_dir", "./output/agent"))
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run(self, company: str, position: str, jd_text: str,
            use_rag: bool = True, render: bool = True) -> Dict:
        """
        运行Agent主循环：生成→审核→修改→再审核，直到通过

        Args:
            company: 公司名
            position: 岗位名
            jd_text: 岗位JD
            use_rag: 是否使用知识库检索
            render: 是否渲染PDF/DOCX

        Returns:
            dict: {
                "final_resume": 最终简历JSON,
                "final_audit": 最终审核结果,
                "iterations": 迭代次数,
                "history": 每轮的简历和审核结果,
                "passed": 是否最终通过,
                "files": 生成的文件路径
            }
        """
        print(f"\n{'#'*60}")
        print(f"# Resume Agent 启动: {company} - {position}")
        print(f"# 目标: 综合评分 >= {self.target_score}, 最大迭代 {self.max_retries} 轮")
        print(f"{'#'*60}")

        history = []
        current_resume = None
        current_audit = None
        passed = False
        files = {}

        for iteration in range(1, self.max_retries + 1):
            print(f"\n{'='*60}")
            print(f"第 {iteration}/{self.max_retries} 轮迭代")
            print(f"{'='*60}")

            # 1. 生成或修改简历
            if iteration == 1:
                # 第一轮：正常生成
                print("\n[步骤1] 生成简历...")
                current_resume = self.generator.generate(
                    company=company,
                    position=position,
                    jd_text=jd_text,
                    use_rag=use_rag
                )
            else:
                # 后续轮次：根据上一轮审核意见修改
                print("\n[步骤1] 根据审核意见修改简历...")
                current_resume = self._revise_resume(
                    resume=current_resume,
                    audit_result=current_audit,
                    jd_text=jd_text,
                    company=company,
                    position=position,
                    iteration=iteration
                )

            # 2. 审核简历
            print("\n[步骤2] 审核简历...")
            current_audit = self.auditor.audit(
                resume_json=current_resume,
                jd_text=jd_text,
                company=company,
                position=position,
                auto_fix=False
            )

            # 记录历史
            history.append({
                "iteration": iteration,
                "resume": copy.deepcopy(current_resume),
                "audit": copy.deepcopy(current_audit),
                "score": current_audit["overall"]["weighted_score"],
                "passed": current_audit["overall"]["passed"]
            })

            # 3. 判断是否通过
            score = current_audit["overall"]["weighted_score"]
            dimension_passed = current_audit["overall"]["passed"]
            passed = dimension_passed and score >= self.target_score

            print(f"\n[本轮结果] 综合评分: {score}/100, 目标: {self.target_score}, "
                  f"维度通过: {'是' if dimension_passed else '否'}, 整体通过: {'是' if passed else '否'}")

            if passed:
                print(f"\n🎉 第 {iteration} 轮审核通过！Agent循环结束。")
                break
            elif iteration < self.max_retries:
                issues = current_audit["overall"]["issues"]
                print(f"\n[分析] 未通过，主要问题:")
                for i, issue in enumerate(issues[:5], 1):
                    print(f"  {i}. {issue}")
                print(f"\n[决策] 进入下一轮迭代，LLM将根据审核意见修改简历...")
            else:
                print(f"\n⚠ 已达最大迭代次数 {self.max_retries}，Agent循环结束。")
                print(f"  最终评分: {score}/100（未达目标 {self.target_score}）")
                print(f"  建议人工审核后手动调整。")

        # 4. 保存最终结果
        if self.auto_save:
            files = self._save_results(
                resume=current_resume,
                audit=current_audit,
                history=history,
                company=company,
                position=position,
                render=render,
                passed=passed
            )

        return {
            "final_resume": current_resume,
            "final_audit": current_audit,
            "iterations": len(history),
            "history": history,
            "passed": passed,
            "final_score": current_audit["overall"]["weighted_score"],
            "files": files
        }

    def _revise_resume(self, resume: Dict, audit_result: Dict, jd_text: str,
                        company: str, position: str, iteration: int) -> Dict:
        """
        根据审核结果修改简历（Agent的核心决策+行动能力）

        Args:
            resume: 当前简历JSON
            audit_result: 审核结果
            jd_text: 岗位JD
            company: 公司名
            position: 岗位名
            iteration: 当前迭代轮次

        Returns:
            dict: 修改后的简历JSON
        """
        # 构建修改提示词
        prompt = self._build_revision_prompt(resume, audit_result, jd_text, company, position, iteration)

        # 调用LLM修改
        try:
            response = self.llm.chat_with_fallback([
                {"role": "system", "content": "你是一位专业的简历优化专家，根据审核意见修改简历，只输出JSON。"},
                {"role": "user", "content": prompt}
            ])
            revised = self.llm.extract_json(response)

            # 保留固定字段（个人信息、教育背景等不应该被修改）
            revised["name"] = resume.get("name", "")
            revised["phone"] = resume.get("phone", "")
            revised["email"] = resume.get("email", "")
            revised["education"] = resume.get("education", {})
            revised["company"] = company
            revised["position"] = position

            # 验证并修复项目角色和时间
            revised = self.generator._build_resume_json(company, position, json.dumps(revised, ensure_ascii=False))

            print(f"  ✓ LLM修改完成")
            return revised

        except Exception as e:
            print(f"  ⚠ LLM修改失败: {e}，保留原简历")
            return resume

    def _build_revision_prompt(self, resume: Dict, audit_result: Dict, jd_text: str,
                                company: str, position: str, iteration: int) -> str:
        """
        构建修改提示词（Agent的"感知→决策"环节，把审核结果转化为修改指令）
        """
        # 提取审核问题
        overall = audit_result.get("overall", {})
        issues = overall.get("issues", [])
        dimension_scores = overall.get("dimension_scores", {})

        # 提取各维度详细问题
        sim_issues = audit_result.get("similarity", {}).get("issues", [])
        truth_issues = audit_result.get("truthfulness", {}).get("issues", [])
        comp_issues = audit_result.get("compliance", {}).get("issues", [])
        llm_suggestions = audit_result.get("llm_audit", {}).get("suggestions", [])
        llm_must_fix = audit_result.get("llm_audit", {}).get("must_fix", [])

        # 提取缺失的关键词
        missing_keywords = audit_result.get("compliance", {}).get("core_missing", [])

        # 简历文本
        resume_text = self.auditor._resume_to_text(resume)

        prompt = f"""你是一位严格的简历优化专家。这是第 {iteration} 轮修改，上一轮审核未通过，请根据审核意见修改简历。

## 目标岗位
公司：{company}
岗位：{position}

## 岗位JD
{jd_text[:1500]}

## 当前简历（需要修改）
{resume_text}

## 上一轮审核结果
综合评分：{overall.get('weighted_score', 0)}/100（目标 >= 70）
维度评分：
  - 相似度: {dimension_scores.get('similarity', 0)}/100
  - 真实性: {dimension_scores.get('truthfulness', 0)}/100
  - 符合度: {dimension_scores.get('compliance', 0)}/100
  - LLM审核: {dimension_scores.get('llm', 0)}/100

## 必须修改的问题（按优先级）
"""

        if llm_must_fix:
            prompt += "### LLM判定必须修改的问题\n"
            for i, issue in enumerate(llm_must_fix, 1):
                prompt += f"{i}. {issue}\n"
            prompt += "\n"

        if truth_issues:
            prompt += "### 真实性问题（需要与知识库素材对齐，不得编造）\n"
            for i, issue in enumerate(truth_issues, 1):
                prompt += f"{i}. {issue}\n"
            prompt += "\n"

        if comp_issues or missing_keywords:
            prompt += "### 符合度问题（需要增加JD关键词）\n"
            for i, issue in enumerate(comp_issues, 1):
                prompt += f"{i}. {issue}\n"
            if missing_keywords:
                prompt += f"缺失的核心关键词: {', '.join(missing_keywords)}\n"
            prompt += "\n"

        if sim_issues:
            prompt += "### 相似度问题（需要调整表述角度，避免照搬）\n"
            for i, issue in enumerate(sim_issues, 1):
                prompt += f"{i}. {issue}\n"
            prompt += "\n"

        if llm_suggestions:
            prompt += "### 修改建议\n"
            for i, sug in enumerate(llm_suggestions, 1):
                prompt += f"{i}. {sug}\n"
            prompt += "\n"

        prompt += """## 修改要求
1. 针对上述问题逐条修改，重点提升真实性和符合度
2. 真实性：经历描述必须有依据，量化数字要合理，不得凭空编造
3. 符合度：在岗位匹配优势、实习经历、项目经历、个人优势中密集嵌入缺失的JD关键词
4. 相似度：调整表述角度，不要照搬模板，根据岗位特点重新组织语言
5. 保持固定信息不变：姓名、电话、邮箱、教育背景
6. 保持项目角色和时间不变：三茶项目=副队长/2023.12-2024.08，医疗项目=组织部部长/2024.12-2025.05
7. 每个经历点仍按「四字总结+STAR+量化」格式
8. 全篇禁止出现"我"字，少用"负责"，多用"统筹/规划/主导"

## 输出格式
只输出JSON，格式如下：
{
  "summary": "修改后的岗位匹配优势",
  "internships": [
    {"org": "公司", "role": "岗位", "time": "时间", "points": [{"kw": "四字总结", "text": "STAR叙述"}]}
  ],
  "projects": [
    {"org": "项目名", "role": "角色", "time": "时间", "points": [{"kw": "四字总结", "text": "STAR叙述"}]}
  ],
  "advantages": ["四字标签：一句话+量化"]
}

只输出JSON，不要输出其他文字。"""

        return prompt

    def _save_results(self, resume: Dict, audit: Dict, history: List[Dict],
                      company: str, position: str, render: bool, passed: bool) -> Dict:
        """保存Agent运行结果"""
        safe_company = re.sub(r'[\\/:*?"<>|]', '_', company)
        safe_position = re.sub(r'[\\/:*?"<>|]', '_', position)
        base_name = f"{safe_company}_{safe_position}_agent"

        files = {}

        # 保存最终简历JSON
        resume_path = self.output_dir / f"{base_name}_final.json"
        with open(resume_path, 'w', encoding='utf-8') as f:
            json.dump(resume, f, ensure_ascii=False, indent=2)
        files["resume_json"] = str(resume_path)

        # 保存最终审核结果
        audit_path = self.output_dir / f"{base_name}_final_audit.json"
        with open(audit_path, 'w', encoding='utf-8') as f:
            json.dump(audit, f, ensure_ascii=False, indent=2)
        files["audit_json"] = str(audit_path)

        # 保存迭代历史（精简版，避免文件过大）
        history_path = self.output_dir / f"{base_name}_history.json"
        history_summary = []
        for h in history:
            history_summary.append({
                "iteration": h["iteration"],
                "score": h["score"],
                "passed": h["passed"],
                "issues_count": len(h["audit"].get("overall", {}).get("issues", [])),
                "dimension_scores": h["audit"].get("overall", {}).get("dimension_scores", {})
            })
        with open(history_path, 'w', encoding='utf-8') as f:
            json.dump(history_summary, f, ensure_ascii=False, indent=2)
        files["history"] = str(history_path)

        # 渲染PDF/DOCX
        if render:
            try:
                # 调用generator的渲染方法
                pdf_path, docx_path = self.generator._render(resume, f"{safe_company}-{safe_position}-{resume.get('name', '')}")
                files["pdf"] = pdf_path
                files["docx"] = docx_path
            except Exception as e:
                print(f"[警告] 渲染失败: {e}")

            # 生成审核报告PDF
            try:
                report_script = Path(__file__).parent.parent / "scripts" / "build_audit_report.py"
                report_dir = self.output_dir
                report_pdf = report_dir / f"{base_name}_审核报告.pdf"
                import subprocess
                import sys
                proc = subprocess.run(
                    [sys.executable, str(report_script), str(audit_path), "-o", str(report_pdf)],
                    capture_output=True, text=True, encoding='utf-8'
                )
                if proc.returncode == 0:
                    files["audit_report_pdf"] = str(report_pdf)
            except Exception as e:
                print(f"[警告] 审核报告生成失败: {e}")

        print(f"\n[保存] Agent运行结果已保存到: {self.output_dir}")
        for key, path in files.items():
            print(f"  {key}: {path}")

        return files
