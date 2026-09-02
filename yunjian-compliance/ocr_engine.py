# -*- coding: utf-8 -*-
"""
OCR 图片文字识别封装
优先使用 PaddleOCR（中文识别最准）。未安装或识别失败时自动降级，
返回友好提示，不影响文本/图片倾向分析。
首次调用会自动下载识别模型（需要联网，一次性）。
"""
import logging
import os
import threading
import time

logger = logging.getLogger("ocr")

_engine = None
_error = None
_lock = threading.Lock()

# Windows 下 Paddle 的 C++ 引擎无法打开含中文的路径（如 C:\Users\小张sharefun\...）。
# 因此在导入 paddleocr 之前，把模型缓存目录重定向到纯 ASCII 路径。
_ASCII_CACHE = r"C:\paddle_cache"


def _redirect_model_cache():
    os.makedirs(_ASCII_CACHE, exist_ok=True)
    os.environ["USERPROFILE"] = _ASCII_CACHE
    os.environ["HOME"] = _ASCII_CACHE


def get_engine():
    """获取（惰性初始化）OCR 引擎。返回 None 表示不可用。"""
    global _engine, _error
    if _engine is not None or _error is not None:
        return _engine
    with _lock:
        # 双重检查：避免多个线程同时初始化
        if _engine is not None or _error is not None:
            return _engine
        try:
            _redirect_model_cache()
            from paddleocr import PaddleOCR
            logger.info("正在初始化 PaddleOCR（首次使用会自动下载模型，请稍候）……")
            _engine = PaddleOCR(
                lang="ch",
                use_angle_cls=True,
                use_gpu=False,
                enable_mkldnn=True,   # CPU 加速
                show_log=False,
            )
            logger.info("PaddleOCR 初始化完成")
        except Exception as e:  # noqa: BLE001
            _error = "OCR 库未正确安装或初始化失败：%s" % e
            logger.error(_error)
            return None
    return _engine


def _extract_text(result):
    """递归提取 PaddleOCR 返回结果中的文字，兼容不同版本的返回结构。"""
    lines = []

    def walk(node):
        if isinstance(node, list):
            # 真正的叶子项形如 [box, (text, confidence)]，其中 node[1][0] 是字符串。
            # 用"第二项的第一个元素是 str"来区分叶子项与整页的 item 列表，避免误判。
            if (len(node) == 2 and isinstance(node[0], list)
                    and isinstance(node[1], (list, tuple))
                    and len(node[1]) >= 1 and isinstance(node[1][0], str)):
                lines.append(node[1][0])
                return
            for sub in node:
                walk(sub)

    walk(result)
    return "".join(lines)


def recognize(image_path):
    """识别图片中的文字。

    返回 (text, note)：
      text  识别出的文字（可能为空字符串）
      note  "OK" 或错误说明
    """
    engine = get_engine()
    if engine is None:
        return "", _error or "OCR 不可用"

    try:
        start = time.time()
        result = engine.ocr(str(image_path), cls=True)
        cost = time.time() - start
        logger.info("OCR 耗时 %.2fs", cost)
        text = _extract_text(result).strip()
        if not text:
            return "", "OK（未识别到文字）"
        return text, "OK"
    except Exception as e:  # noqa: BLE001
        logger.exception("OCR 识别失败")
        return "", "OCR 识别失败：%s" % e
