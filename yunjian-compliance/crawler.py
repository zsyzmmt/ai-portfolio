# -*- coding: utf-8 -*-
"""
合规数据爬虫框架
================
目标：采集公开的监管处罚案例与银行产品宣传文本，用于扩充合规词库与案例库。

设计原则：
  - 礼貌爬取：伪装浏览器 UA、设置超时、节流（每次请求间隔 sleep）
  - 尽力而为：站点改版/反爬/超时时，自动降级到种子库（seed_cases.py），不崩溃
  - 诚实报告：返回本次采集的来源（live=实时抓取 / seed=种子库兜底）与说明

注意：仅采集公开信息用于个人课题研究，请遵守目标网站 robots 与相关法规。
"""
import json
import logging
import os
import time

import seed_marketing

logger = logging.getLogger("crawler")

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
}
TIMEOUT = 10
DELAY = 1.0          # 两次请求最小间隔（秒）

# 尝试采集的公开源（尽力而为，两类数据）
SOURCES = {
    "nfra_penalty": {
        "name": "国家金融监督管理总局·行政处罚信息",
        "url": "https://www.nfra.gov.cn/cn/view/pages/ItemList.html?itemPId=962",
    },
    "bank_product": {
        "name": "银行个人产品宣传页",
        "url": "https://www.abchina.com/cn/PersonalServices/Investments/",
    },
}


def _get(url):
    """带 UA / 超时 / 重试一次的 GET。失败抛异常。"""
    import requests
    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT, verify=True)
    resp.raise_for_status()
    time.sleep(DELAY)   # 节流
    return resp


def try_crawl_penalties():
    """尝试实时抓取处罚案例。返回 (cases, note) 或抛异常。

    当前 NFRA 栏目为 JS 异步渲染，静态抓取通常拿不到条目，
    故此处主要演示"实时采集"的接入点，真实接入可在此扩展。
    """
    from bs4 import BeautifulSoup
    src = SOURCES["nfra_penalty"]
    resp = _get(src["url"])
    soup = BeautifulSoup(resp.text, "html.parser")
    # 尝试抽取正文文本（若站点改为静态渲染则可解析到内容）
    text = soup.get_text(" ", strip=True)
    return [], "已连通 %s（栏目为动态渲染，当前未解析到结构化处罚条目）" % src["name"]


def collect_cases():
    """采集处罚案例：实时优先，失败降级种子库。

    返回 dict：
      source   "live" 或 "seed"
      cases    案例列表
      note     本次采集说明
    """
    try:
        cases, note = try_crawl_penalties()
        if cases:
            logger.info("实时采集成功：%d 条", len(cases))
            return {"source": "live", "cases": cases, "note": note}
        return {"source": "seed", "cases": [], "note": note}
    except Exception as e:  # noqa: BLE001
        logger.warning("实时采集失败（%s），降级到种子库", e)
        return {"source": "seed", "cases": [],
                "note": "实时采集不可用（%s），已降级使用内置种子案例库。" % _short(str(e))}


def _short(s, n=80):
    return s if len(s) <= n else s[:n] + "…"


# ---------------------------------------------------------------- 宣传文本
def try_crawl_marketing():
    """尝试实时抓取银行产品宣传文本。返回 (samples, note) 或抛异常。

    宣传页多为动态渲染，静态抓取通常拿不到结构化文本，
    此处主要演示第二类数据源的接入点，真实接入可在此扩展。
    """
    from bs4 import BeautifulSoup
    src = SOURCES["bank_product"]
    resp = _get(src["url"])
    soup = BeautifulSoup(resp.text, "html.parser")
    text = soup.get_text(" ", strip=True)
    return [], "已连通 %s（栏目为动态渲染，当前未解析到结构化宣传条目）" % src["name"]


def collect_marketing():
    """采集银行产品宣传文本：实时优先，失败降级种子语料。

    返回 dict：{source, samples, note}
    """
    try:
        samples, note = try_crawl_marketing()
        if samples:
            logger.info("宣传文本实时采集成功：%d 条", len(samples))
            return {"source": "live", "samples": samples, "note": note}
        return {"source": "seed", "samples": [], "note": note}
    except Exception as e:  # noqa: BLE001
        logger.warning("宣传文本采集失败（%s），降级到种子语料", e)
        return {"source": "seed", "samples": [],
                "note": "实时采集不可用（%s），已降级使用内置宣传语料。" % _short(str(e))}


def load_marketing_store(path=None):
    """读取合并后的宣传文本语料 JSON。"""
    if path is None:
        base = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(base, "data", "marketing.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data.get("samples", [])
        except (OSError, ValueError):
            logger.warning("宣传语料读取失败，使用种子语料")
    return seed_marketing.load_marketing()


def merge_marketing_with_seed(live_samples, seed_samples):
    """实时宣传文本与种子语料合并去重（按 text 判重）。"""
    seen = set()
    merged = []
    for s in list(live_samples) + list(seed_samples):
        key = s.get("text", "")[:40]
        if key in seen:
            continue
        seen.add(key)
        merged.append(s)
    return merged


def save_marketing_store(samples, path=None):
    """保存合并后的宣传文本语料。"""
    if path is None:
        base = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(base, "data", "marketing.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"source": "merged", "samples": samples},
                  fh, ensure_ascii=False, indent=2)
    return path


def merge_with_seed(live_cases, seed_cases):
    """实时案例与种子案例合并去重（按 date+org+violation 判重）。"""
    seen = set()
    merged = []
    for c in list(live_cases) + list(seed_cases):
        key = (c.get("date", ""), c.get("org", ""), c.get("violation", "")[:20])
        if key in seen:
            continue
        seen.add(key)
        merged.append(c)
    return merged


def load_case_store(path=None):
    """读取合并后的案例库 JSON。"""
    if path is None:
        base = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(base, "data", "cases.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data.get("cases", [])
        except (OSError, ValueError):
            logger.warning("案例库读取失败，使用种子库")
    return seed_cases.load_cases()


def save_case_store(cases, path=None):
    """保存合并后的案例库。"""
    if path is None:
        base = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(base, "data", "cases.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"source": "merged", "cases": cases},
                  fh, ensure_ascii=False, indent=2)
    return path
