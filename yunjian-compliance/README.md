# 云鉴 · 员工言论合规分析 Agent

输入员工言论（文本或图片），自动完成：**特征分析 → 结构化 → 合规风险识别 → 整改建议生成**。支持图片文字识别（OCR）和图片色彩倾向分析。

> 面向银行零售合规场景的课题项目：把"员工朋友圈营销文案人工审核低效、关键词检索易遗漏"的业务问题，转化为可运行、可解释、可审计的合规分析系统。

## 为什么用规则引擎而非黑盒大模型

银行合规场景对**可解释性**和**可审计性**有硬要求——每条判定都要能追溯到触发词和规则，才能向监管说明。因此本项目采用**本地纯规则引擎**（关键词 + 否定 + 程度副词），离线运行、结果可解释：
- 每一条违规判定都能说出"命中了哪条规则、哪个关键词"
- 无网络依赖，敏感言论不外传
- 词库可随合规制度动态增删，刷新即生效

架构上预留了"规则兜底 + 大模型增强"双引擎的演进方向：规则引擎保证可解释底线，大模型补足语义泛化。

## 功能

| 输入 | 处理 | 输出 |
|---|---|---|
| 文本（粘贴或 .txt/.md/.csv/.log 文件） | 中文情感分析引擎 | 负面/中性/正面 + 负面风险 0~100 + 特征词 |
| 文本 | 合规风险检测 | 8 类合规风险 + 等级（高/中/低）+ 整改建议 |
| 图片（.png/.jpg/.bmp/.webp） | OCR 提取文字 → 情感 + 合规分析 | 同上 + OCR 原文 |
| 图片 | 色彩/亮度特征分析 | 压抑指数 0~100 + 倾向描述 |
| 批量 CSV | 批量分析 + 风险档案累计 | 员工个人风险档案 + 高危预警 |

### 8 类合规风险

私售飞单 · 违规承诺收益 · 夸大/绝对化宣传 · 客户信息泄露 · 红线操作（代客/共享）· 洗钱套现 · 私下返佣 · 情绪负面

每类风险配置了 `severity`（严重级别）、`keywords`（触发词）、`suggestion`（整改建议），完整定义在 `compliance_rules.py`。

### 数据闭环进化

```
监管案例爬取 → 风险词库自动提炼 → 规则库增量更新 → 员工风险档案跨批次累计 → 高危预警
```

`crawler.py` 自动采集监管处罚案例，`rule_miner.py` 从案例中提炼新风险词并回填词库，形成"案例 → 词库 → 规则"的自我进化闭环。

## 目录结构

```
yunjian-compliance/
├── app.py               # Flask Web 服务（输入分析 + 批量看板 + 风险档案）
├── batch.py             # 批量 CSV 分析
├── compliance.py        # 合规分析入口
├── compliance_rules.py  # 8 类风险规则库（severity/keywords/suggestion）
├── compliance_custom.py # 自定义规则扩展
├── crawler.py           # 监管案例采集
├── rule_miner.py        # 案例→风险词自动提炼
├── sentiment.py         # 中文情感分析（关键词+否定+程度副词）
├── keywords.py          # 情感词库
├── ocr_engine.py        # PaddleOCR 图片文字识别（中文路径缓存重定向）
├── image_analyzer.py    # 图片色彩/亮度倾向分析
├── profile_store.py     # 员工风险档案跨批次累计 + 高危预警
├── screen_capture.py    # 屏幕截图分析
├── make_test_images.py  # 生成测试图片
├── demo_batch.csv       # 演示批量数据（化名）
├── data/                # 示例数据（监管案例 / 营销语料 / 员工档案，均脱敏）
└── requirements.txt
```

## 环境与安装

- Windows，Python 3.8（本机位于 `C:\Python3\python.exe`）
- 首次使用 OCR 需联网下载识别模型（一次性，约 20MB）

```bat
:: 1. 升级 pip（Python 3.8 用 24.3.1，25.x 需要 Python 3.9+）
C:\Python3\python.exe -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple "pip==24.3.1"

:: 2. 安装依赖（paddle 较大，耐心等待；国内建议用清华镜像）
C:\Python3\python.exe -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
```

## 运行

```bat
C:\Python3\python.exe app.py
```

浏览器打开 <http://127.0.0.1:5000>，粘贴文本或上传文件即可。

## 测试

```bat
:: 生成测试图片（含中文文字的图片 + 明暗图）
C:\Python3\python.exe make_test_images.py
```

上传 `test_images\` 里的图片到网页即可验证。

## 说明

- 情感分析为**本地纯规则引擎**（关键词 + 否定 + 程度副词），离线运行、结果可解释，但精度依赖词库丰富度。
- 图片倾向分析为**色彩/亮度特征的简化分析**，不含语义内容理解；图片有文字时以 OCR 情感结果为准。
- OCR 失败不会影响文本分析，页面会给出友好提示。
- **关于 OCR 模型缓存**：Paddle 引擎在含中文的路径（如用户名含中文）下无法加载模型，程序已自动将模型缓存重定向到纯英文路径，无需手动处理。

## 技术栈

Python · Flask · PaddleOCR 2.7.3 · 自研规则引擎 · 情感分析 · 案例爬虫
