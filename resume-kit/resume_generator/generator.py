#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简历生成器：整合知识库检索 + LLM生成 + JSON输出 + PDF/DOCX渲染
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Dict, Optional, Any

from .llm_client import LLMClient


class ResumeGenerator:
    """简历生成器"""

    def __init__(self, config: Dict, knowledge_base=None, llm_client=None):
        """
        Args:
            config: 完整配置字典
            knowledge_base: KnowledgeBase实例（可选，不提供则不使用RAG）
            llm_client: LLMClient实例（可选，不提供则根据config创建）
        """
        self.config = config
        self.kb = knowledge_base
        self.llm = llm_client or LLMClient(config.get("llm", {}))

        resume_config = config.get("resume", {})
        self.user_info = {
            "name": resume_config.get("name", "候选人"),
            "phone": resume_config.get("phone", ""),
            "email": resume_config.get("email", ""),
            "education": resume_config.get("education", {})
        }
        self.output_dir = Path(resume_config.get("output_dir", "./output"))
        self.max_pages = resume_config.get("max_pages", 1)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # 项目固定元信息
        self.project_meta = {
            "sancha": {
                "org": "云时茶烟·数字化赋能福建\"三茶+康养\"政策发展项目",
                "role": "副队长",
                "time": "2023.12-2024.08"
            },
            "yiliao": {
                "org": "诊心同行·一站式志愿康养系统",
                "role": "组织部部长",
                "time": "2024.12-2025.05"
            },
            "chaye": {
                "org": "中国茶叶产业\"量增价跌\"悖论归因分析",
                "role": "独立完成",
                "time": "2026.01-2026.02"
            }
        }

    # ============================================================
    # 主流程
    # ============================================================
    def generate(self, company: str, position: str, jd_text: str,
                 use_rag: bool = True, top_k: int = 8) -> Dict:
        """
        生成完整简历

        Args:
            company: 公司名
            position: 岗位名
            jd_text: 岗位JD文本
            use_rag: 是否使用知识库检索
            top_k: 检索返回的相关经历数量

        Returns:
            dict: 完整的简历JSON
        """
        print(f"\n{'='*60}")
        print(f"生成简历: {company} - {position}")
        print(f"{'='*60}")

        # 1. 提取JD关键词
        jd_keywords = self._extract_jd_keywords(jd_text)
        print(f"\n[1/5] JD关键词提取完成")
        print(f"  硬技能: {', '.join(jd_keywords['hard_skills'][:10])}")
        print(f"  软技能: {', '.join(jd_keywords['soft_skills'][:10])}")

        # 2. 检索相关经历
        relevant_experiences = []
        if use_rag and self.kb:
            relevant_experiences = self._retrieve_experiences(jd_text, jd_keywords, top_k)
            print(f"\n[2/5] 知识库检索完成，找到 {len(relevant_experiences)} 段相关经历")
        else:
            print(f"\n[2/5] 跳过知识库检索（use_rag={use_rag}, kb={self.kb is not None}）")

        # 3. 构建提示词
        prompt = self._build_prompt(company, position, jd_text, jd_keywords, relevant_experiences)
        print(f"\n[3/5] 提示词构建完成（长度: {len(prompt)} 字符）")

        # 4. 调用LLM生成
        print(f"\n[4/5] 调用LLM生成简历内容...")
        resume_content = self._call_llm(prompt)
        print(f"  生成完成（长度: {len(resume_content)} 字符）")

        # 5. 解析并构建完整JSON
        print(f"\n[5/5] 解析生成内容并构建简历JSON...")
        resume_json = self._build_resume_json(company, position, resume_content)
        print(f"  实习经历: {len(resume_json['internships'])} 段")
        print(f"  项目经历: {len(resume_json['projects'])} 段")
        print(f"  个人优势: {len(resume_json['advantages'])} 条")

        return resume_json

    def generate_and_save(self, company: str, position: str, jd_text: str,
                          use_rag: bool = True, render: bool = True) -> Dict:
        """
        生成简历并保存为JSON/PDF/DOCX

        Args:
            company: 公司名
            position: 岗位名
            jd_text: 岗位JD文本
            use_rag: 是否使用知识库检索
            render: 是否渲染PDF/DOCX

        Returns:
            dict: {"json": path, "pdf": path, "docx": path, "resume": resume_json}
        """
        # 生成简历
        resume_json = self.generate(company, position, jd_text, use_rag)

        # 文件名
        safe_company = self._sanitize_filename(company)
        safe_position = self._sanitize_filename(position)
        base_name = f"{safe_company}-{safe_position}-{self.user_info['name']}"

        # 保存JSON
        json_path = self.output_dir / f"{base_name}.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(resume_json, f, ensure_ascii=False, indent=2)
        print(f"\nJSON已保存: {json_path}")

        result = {"json": str(json_path), "pdf": None, "docx": None, "resume": resume_json}

        # 渲染PDF/DOCX
        if render:
            try:
                pdf_path, docx_path = self._render(resume_json, base_name)
                result["pdf"] = pdf_path
                result["docx"] = docx_path
            except Exception as e:
                print(f"[警告] 渲染失败: {e}")
                print("  可手动运行: python scripts/build_pdf.py <json> -o <pdf> --max-pages 1")

        return result

    # ============================================================
    # JD关键词提取
    # ============================================================
    def _extract_jd_keywords(self, jd_text: str) -> Dict:
        """从JD文本中提取关键词"""
        keywords = {"hard_skills": [], "soft_skills": [], "requirements": [], "bonus": []}

        # 简化版关键词词典
        keyword_dict = {
            "hard_skills": [
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
                "文档撰写", "工作总结", "汇报材料", "演示文稿", "预算", "绩效"
            ],
            "soft_skills": [
                "沟通协调", "跨部门", "团队合作", "团队管理", "统筹", "规划",
                "组织能力", "执行力", "抗压", "学习能力", "适应能力",
                "逻辑思维", "分析能力", "解决问题", "创新", "文案撰写",
                "文档撰写", "会议纪要", "汇报", "演讲", "谈判", "客户服务",
                "商务拓展", "时间管理", "多任务", "细致", "严谨", "责任心",
                "保密", "职业素养", "文字功底", "表达能力", "人际交往",
                "资源整合", "推动", "落地", "闭环", "复盘", "迭代",
                "主动", "积极", "稳重", "踏实", "可靠", "敏锐", "洞察",
                "沟通", "协作", "协调", "统筹规划"
            ],
            "requirements": [
                "本科", "硕士", "博士", "985", "211", "双一流", "应届",
                "实习生", "1年", "2年", "3年", "5年", "经验", "持证",
                "证书", "英语", "CET-4", "CET-6", "雅思", "托福", "驾照",
                "普通话"
            ],
            "bonus": [
                "优先", "加分", "有经验者", "熟悉", "了解", "掌握", "精通",
                "有热情", "有兴趣", "基础知识", "相关经验", "项目经验",
                "实习经验", "学生组织", "助理", "项目管理类"
            ]
        }

        jd_lower = jd_text.lower()
        for category, words in keyword_dict.items():
            for word in words:
                if word.lower() in jd_lower and word not in keywords[category]:
                    keywords[category].append(word)

        return keywords

    # ============================================================
    # 知识库检索
    # ============================================================
    def _retrieve_experiences(self, jd_text: str, jd_keywords: Dict, top_k: int) -> List[Dict]:
        """从知识库检索相关经历"""
        if not self.kb:
            return []

        # 构建查询文本：JD核心关键词组合
        query_parts = []
        query_parts.extend(jd_keywords["hard_skills"][:10])
        query_parts.extend(jd_keywords["soft_skills"][:5])
        query = " ".join(query_parts) + " " + jd_text[:500]

        # 检索
        results = self.kb.search(query, top_k=top_k)

        # 格式化
        formatted = []
        for r in results:
            formatted.append({
                "source": r["source"],
                "score": r["score"],
                "text": r["text"][:800]  # 限制长度，避免提示词过长
            })

        return formatted

    # ============================================================
    # 提示词构建
    # ============================================================
    def _build_prompt(self, company: str, position: str, jd_text: str,
                      jd_keywords: Dict, relevant_experiences: List[Dict]) -> str:
        """构建LLM提示词"""

        # 系统提示
        system_prompt = f"""你是一位专业的简历优化专家，擅长根据目标岗位JD重写中文简历。

## 候选人固定信息
- 姓名：{self.user_info['name']}
- 电话：{self.user_info['phone']}
- 邮箱：{self.user_info['email']}
- 教育：{self.user_info['education'].get('school', '')} {self.user_info['education'].get('major', '')} {self.user_info['education'].get('time', '')}
- 亮点：{self.user_info['education'].get('detail', '')}

## 固定项目信息（角色和时间不可修改）
1. 三茶项目：{self.project_meta['sancha']['org']}，角色：{self.project_meta['sancha']['role']}，时间：{self.project_meta['sancha']['time']}
2. 医疗项目：{self.project_meta['yiliao']['org']}，角色：{self.project_meta['yiliao']['role']}，时间：{self.project_meta['yiliao']['time']}
3. 茶叶分析：{self.project_meta['chaye']['org']}，角色：{self.project_meta['chaye']['role']}，时间：{self.project_meta['chaye']['time']}

## 写作规则（必须严格遵守）
1. 每个经历点格式：「四字总结：背景→行动→结果」的一段式STAR叙事
2. 每个点必须隐含S（背景/痛点）、T（目标）、A（行动）、R（量化结果）
3. 每个点至少含1个量化数字
4. 全篇禁止出现"我"字，省略主语，动作直接以主动动词开头
5. 少用"负责/参与/协助"，多用"统筹/规划/主导/搭建/推动/落地/沉淀/赋能/驱动"
6. 不要标注(S)(T)(A)(R)字母
7. 个人信息只写姓名、电话、邮箱，不写其他
8. 不设荣誉奖项板块
9. 删除"校园线上社区运营"和"AI财报"项目
10. AI审核经历补入中国银行实习
11. 泉州大剧院销售实习作为独立实习经历
12. 茶叶产业分析作为独立项目经历

## 输出格式
只输出JSON，不要输出其他文字。JSON格式如下：
{{
  "summary": "岗位匹配优势段落（2-3句，密集嵌入JD关键词）",
  "internships": [
    {{
      "org": "公司名",
      "role": "岗位名",
      "time": "起止时间",
      "points": [
        {{"kw": "四字总结", "text": "STAR叙述文本"}}
      ]
    }}
  ],
  "projects": [
    {{
      "org": "项目名（必须使用固定项目名）",
      "role": "角色（必须使用固定角色）",
      "time": "时间（必须使用固定时间）",
      "points": [
        {{"kw": "四字总结", "text": "STAR叙述文本"}}
      ]
    }}
  ],
  "advantages": [
    "四字标签：一句话+量化佐证"
  ]
}}"""

        # 用户提示
        user_prompt = f"""## 目标岗位
公司：{company}
岗位：{position}

## 岗位JD
{jd_text}

## JD核心关键词
硬技能：{', '.join(jd_keywords['hard_skills'][:15])}
软技能：{', '.join(jd_keywords['soft_skills'][:10])}
硬性要求：{', '.join(jd_keywords['requirements'][:10])}
加分项：{', '.join(jd_keywords['bonus'][:10])}
"""

        # 添加检索到的相关经历
        if relevant_experiences:
            user_prompt += f"""
## 知识库检索到的相关经历素材（请优先参考这些内容重写，不要直接复制，要按STAR法则重组）
"""
            for i, exp in enumerate(relevant_experiences, 1):
                user_prompt += f"""
### 经历素材{i}（来源：{exp['source']}，相关度：{exp['score']}）
{exp['text']}
"""

        user_prompt += """
## 任务
请根据以上岗位JD和经历素材，重写一份高匹配度的中文简历。要求：
1. 岗位匹配优势段落密集嵌入JD关键词
2. 实习经历和项目经历的每个点都按「四字总结+STAR+量化」重写
3. 个人优势4条左右，每条=四字标签+一句话+量化佐证
4. 只输出JSON，不要输出其他文字、解释或markdown代码块标记"""

        return system_prompt + "\n\n" + user_prompt

    # ============================================================
    # LLM调用
    # ============================================================
    def _call_llm(self, prompt: str) -> str:
        """调用LLM生成简历内容"""
        messages = [
            {"role": "system", "content": "你是一位专业的简历优化专家，只输出JSON，不输出其他文字。"},
            {"role": "user", "content": prompt}
        ]

        # 使用带降级的调用（当前模型失败时自动切换备用模型）
        return self.llm.chat_with_fallback(messages)

    # ============================================================
    # JSON构建与验证
    # ============================================================
    def _build_resume_json(self, company: str, position: str, llm_output: str) -> Dict:
        """从LLM输出构建完整简历JSON"""
        # 提取JSON
        try:
            content = self.llm.extract_json(llm_output)
        except ValueError as e:
            print(f"[警告] JSON解析失败: {e}")
            print("  使用原始输出作为fallback")
            content = {"summary": "", "internships": [], "projects": [], "advantages": []}

        # 构建完整JSON
        resume = {
            "company": company,
            "position": position,
            "name": self.user_info["name"],
            "phone": self.user_info["phone"],
            "email": self.user_info["email"],
            "summary": content.get("summary", ""),
            "education": self.user_info["education"],
            "internships": content.get("internships", []),
            "projects": content.get("projects", []),
            "advantages": content.get("advantages", [])
        }

        # 验证并修复项目角色和时间
        for proj in resume["projects"]:
            org = proj.get("org", "")
            if "三茶" in org or "云时茶烟" in org:
                proj["role"] = self.project_meta["sancha"]["role"]
                proj["time"] = self.project_meta["sancha"]["time"]
            elif "诊心" in org:
                proj["role"] = self.project_meta["yiliao"]["role"]
                proj["time"] = self.project_meta["yiliao"]["time"]
            elif "茶叶产业" in org or "量增价跌" in org:
                proj["role"] = self.project_meta["chaye"]["role"]
                proj["time"] = self.project_meta["chaye"]["time"]

        # 验证禁用词
        self._validate_resume(resume)

        return resume

    def _validate_resume(self, resume: Dict) -> Dict:
        """验证简历合规性，返回问题列表"""
        issues = []
        all_text = self._get_resume_text(resume)

        # 检查"我"字
        wo_count = all_text.count("我")
        if wo_count > 0:
            issues.append(f"全文出现'我'字 {wo_count} 次")

        # 检查"负责"
        fz_count = all_text.count("负责")
        if fz_count > 1:
            issues.append(f"全文出现'负责' {fz_count} 次（建议少用）")

        # 检查禁用项目
        for forbidden in ["校园线上社区运营", "AI财报", "AI 赋能财报"]:
            if forbidden in all_text:
                issues.append(f"包含禁用项目: {forbidden}")

        # 检查经历点格式
        all_points = []
        for intern in resume.get("internships", []):
            all_points.extend(intern.get("points", []))
        for proj in resume.get("projects", []):
            all_points.extend(proj.get("points", []))

        for i, point in enumerate(all_points):
            kw = point.get("kw", "")
            text = point.get("text", "")
            if len(kw) != 4:
                issues.append(f"经历点{i+1}的四字总结'{kw}'不是4个字")
            if not re.search(r'\d', text):
                issues.append(f"经历点{i+1}（{kw}）缺少量化数字")

        if issues:
            print(f"[验证] 发现 {len(issues)} 个问题:")
            for issue in issues:
                print(f"  ⚠ {issue}")
        else:
            print("[验证] 简历合规，未发现问题")

        return {"issues": issues, "valid": len(issues) == 0}

    def _get_resume_text(self, resume: Dict) -> str:
        """获取简历全文本"""
        parts = [resume.get("summary", "")]
        for intern in resume.get("internships", []):
            parts.append(intern.get("org", ""))
            parts.append(intern.get("role", ""))
            for p in intern.get("points", []):
                parts.append(p.get("kw", ""))
                parts.append(p.get("text", ""))
        for proj in resume.get("projects", []):
            parts.append(proj.get("org", ""))
            parts.append(proj.get("role", ""))
            for p in proj.get("points", []):
                parts.append(p.get("kw", ""))
                parts.append(p.get("text", ""))
        for adv in resume.get("advantages", []):
            parts.append(adv)
        return " ".join(parts)

    # ============================================================
    # 渲染
    # ============================================================
    def _render(self, resume_json: Dict, base_name: str) -> tuple:
        """渲染PDF和DOCX"""
        # 查找渲染脚本
        script_dirs = [
            Path(__file__).parent.parent / "scripts",
            Path.cwd() / "scripts",
        ]

        build_docx = None
        build_pdf = None
        for d in script_dirs:
            if (d / "build_docx.py").exists():
                build_docx = d / "build_docx.py"
            if (d / "build_pdf.py").exists():
                build_pdf = d / "build_pdf.py"

        if not build_docx or not build_pdf:
            raise FileNotFoundError("未找到渲染脚本 build_docx.py / build_pdf.py")

        # 保存临时JSON
        temp_json = self.output_dir / f"{base_name}.json"
        with open(temp_json, 'w', encoding='utf-8') as f:
            json.dump(resume_json, f, ensure_ascii=False, indent=2)

        pdf_path = self.output_dir / f"{base_name}.pdf"
        docx_path = self.output_dir / f"{base_name}.docx"

        # 生成DOCX
        proc = subprocess.run(
            [sys.executable, str(build_docx), str(temp_json), "-o", str(docx_path)],
            capture_output=True, text=True, encoding='utf-8'
        )
        if proc.returncode != 0:
            print(f"[警告] DOCX生成: {proc.stderr}")

        # 生成PDF
        proc = subprocess.run(
            [sys.executable, str(build_pdf), str(temp_json), "-o", str(pdf_path), "--max-pages", str(self.max_pages)],
            capture_output=True, text=True, encoding='utf-8'
        )
        if proc.returncode != 0:
            print(f"[警告] PDF生成: {proc.stderr}")

        print(f"PDF已保存: {pdf_path}")
        print(f"DOCX已保存: {docx_path}")

        return str(pdf_path), str(docx_path)

    # ============================================================
    # 工具方法
    # ============================================================
    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """清理文件名中的非法字符"""
        return re.sub(r'[\\/:*?"<>|]', '_', name).strip()
