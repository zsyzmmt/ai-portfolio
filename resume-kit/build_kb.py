#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""扩知识库 V3：按经历点切块，直接对 md 素材调用 _chunk_text 分块（绕过 PDF 解析的断行合并），重建 FAISS 索引。"""
import os
import re
import sys
import json
import hashlib
from pathlib import Path

KB_DIR = Path(r"C:\Users\小张sharefun\Doubao\chats\2026-08-28\new-chat-1\resume-kit")
SKILL_REF = Path(r"C:\Users\小张sharefun\AppData\Local\Doubao\User Data\Default\.doubao\agent_mode\workspace\.user_skills\resume-writer\references")

# 素材映射：文档标识 -> md素材
SOURCES = [
    ("三茶项目_STAR拆解.pdf", SKILL_REF / "云时茶烟_STAR素材.md"),
    ("诊心同行_STAR拆解.pdf", SKILL_REF / "诊心同行_STAR素材.md"),
    ("补充经历素材.pdf", SKILL_REF / "补充经历素材.md"),
    ("基础简历.pdf", SKILL_REF / "基础简历_当前版本.md"),
]

# 经历点边界：编号点 / 章节标题 / bullet 列表
POINT_BOUNDARY = re.compile(r"^\s*(\d+\.\s|\d+\.\s*\S|#+\s|-\s|·\s|◆\s)")


def preprocess_md(text: str) -> str:
    """去 page 分隔，在每个经历点边界前插空行，让 _chunk_text 按点分块。"""
    lines = []
    for line in text.splitlines():
        if line.strip().startswith("--- page"):
            continue
        stripped = line.strip()
        if stripped and POINT_BOUNDARY.match(stripped) and lines and lines[-1].strip():
            lines.append("")  # 点边界前插空行
        lines.append(line)
    return "\n".join(lines)


def main():
    os.chdir(KB_DIR)
    sys.path.insert(0, str(KB_DIR))
    from knowledge_base.manager import KnowledgeBase

    # 清空旧索引（保留 pdfs 文件）
    for sub in ["chunks", "faiss_index"]:
        for f in ["chunks.json", "index.faiss", "index.npy", "index_meta.json"]:
            p = KB_DIR / "data" / sub / f
            if p.exists():
                p.unlink()
    print("[清理] 旧 chunks + 索引已删除")

    kb = KnowledgeBase(data_dir=str(KB_DIR / "data"))

    # 先通过 add_pdf 加入已有的 AI简历Agent项目_经历总结.pdf（走真实 PDF 解析）
    kb.add_pdf(str(KB_DIR / "data" / "pdfs" / "AI简历Agent项目_经历总结.pdf"), rebuild_index=False)

    # 再对 4 份 md 素材直接分块
    for name, md_path in SOURCES:
        if not md_path.exists():
            print(f"[跳过] 素材不存在: {md_path}")
            continue
        text = preprocess_md(md_path.read_text(encoding="utf-8"))
        fake = {"filename": name, "full_text": text, "page_count": 1}
        chunks = kb._chunk_text(fake)
        # 移除该文档旧块
        kb._chunks = [c for c in kb._chunks if c.get("source") != name]
        kb._chunks.extend(chunks)
        kb._doc_hashes[name] = "manual-" + hashlib.md5(text.encode("utf-8")).hexdigest()
        print(f"[素材] {name} -> {len(chunks)} 个文本块")

    kb._save_chunks()

    # 重建索引
    kb.build_index()

    # 统计
    stats = kb.stats()
    print("\n===== 知识库统计 =====")
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    print("\n===== 分块明细 =====")
    from collections import Counter
    cnt = Counter(c["source"] for c in kb._chunks)
    for src, n in cnt.items():
        print(f"  {src}: {n} 块")

    # 检索验证
    for q in ["自我纠偏 自动重写 审核", "问卷设计 消费者 购茶 行为", "陪诊 志愿者 医院 挂号 服务", "量增价跌 归因 茶叶 出口 价效应", "销售 定价 SKU 剧院 滞销", "合规审核 文案 大模型 双轨"]:
        print(f"\n===== 检索: {q} =====")
        for r in kb.search(q, top_k=3):
            print(f"  [{r['score']:.3f}] {r['source']} | {r['text'][:55]}...")


if __name__ == "__main__":
    main()
