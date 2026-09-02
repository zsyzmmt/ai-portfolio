# Resume Kit — AI 简历生成与审核 Agent

针对秋招简历"量化难、匹配度低、信息失真"三大痛点，独立设计并开发的自带自我纠偏能力的 AI 简历写作工具。输入岗位 JD，自动完成 **检索 → 生成 → 评估 → 重写** 闭环，单份定制化简历分钟级交付（PDF + DOCX + 审核报告）。

## 核心能力

| 能力 | 实现 | 效果 |
|---|---|---|
| **Agent 闭环** | "检索-生成-评估-重写"4 大模块，生成→审核→不达标→重写 | 最多 3 轮循环直至通过阈值，多岗位真实跑通 |
| **RAG 知识增强** | 私有知识库切片向量化（64 个语义分块），FAISS 向量库 + Embedding Top-K 召回 | 跨文档精准上下文匹配，内容真实可追溯 |
| **防幻觉结构锁定** | 简历解析为结构化 JSON，姓名/电话/邮箱/教育等关键字段代码级硬隔离锁定，LLM 输出后强制覆盖 | 事实数据篡改率压降至 0% |
| **多维质检** | 文本相似度（防照搬）/ 知识库召回率（防失真）/ JD 关键词匹配（防偏离）三维打分 + LLM 深度审核 | STAR 覆盖率与数据量化率稳定达标 |
| **协议封装** | 兼容 OpenAI/Anthropic/DeepSeek 3 类 LLM 协议，多模型自动容灾；纯 Python 标准库 HTTP API + MCP 双传输（SSE / Streamable） | 任意支持 MCP/HTTP 平台可无缝调用 |

## 模块结构

```
resume-kit/
├── resume_generator/
│   ├── agent.py        # Agent 自主循环：生成→审核→重写直到通过
│   ├── generator.py    # 生成器：知识库检索 + LLM 生成 + JSON + PDF/DOCX 渲染
│   ├── auditor.py      # 审核器：三维质检（相似度/召回率/JD 匹配）+ LLM 深度审核
│   └── llm_client.py   # 多模型客户端：OpenAI 兼容 + Anthropic Claude，自动容灾切换
├── knowledge_base/
│   ├── manager.py      # 知识库：PDF 解析、文本分块、向量化、FAISS 存储、语义检索
│   └── pdf_parser.py   # PDF 解析器
├── api_server.py       # HTTP API 服务（纯标准库）+ MCP 双协议（SSE/Streamable）
├── build_kb.py         # 知识库构建脚本（按经历点切块 + FAISS 索引）
├── config.example.yaml # 配置示例（复制为 config.yaml 填入自己的 API Key）
└── examples/           # 真实运行产物：网易互娱岗位 3 轮"生成-审核-重写"迭代
```

## 运行

```bash
# 1. 配置
cp config.example.yaml config.yaml   # 填入自己的 LLM API Key

# 2. 安装依赖
pip install -r requirements.txt      # faiss-cpu / sentence-transformers / pymupdf / python-docx / reportlab

# 3. 构建知识库（可选，已有默认知识库）
python build_kb.py

# 4. 启动 HTTP + MCP 服务
python api_server.py

# 或直接命令行生成
python -m resume_generator.agent --jd path/to/jd.txt
```

> 依赖较重（sentence-transformers 需 torch）；如环境受限，`knowledge_base/manager.py` 内置 TF-IDF 纯 numpy 回退分支，轻量可跑。

## 真实运行证据

`examples/` 目录保存了网易互娱品牌管理培训生岗位的 3 轮 Agent 迭代 JSON——每轮包含生成结果、审核打分、重写内容，完整呈现"生成-评估-反馈"闭环的实际执行过程。

## 技术栈

Python · FAISS · sentence-transformers · RAG · Agent · MCP（SSE + Streamable HTTP）· python-docx · reportlab · PyMuPDF
