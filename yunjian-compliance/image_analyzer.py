# -*- coding: utf-8 -*-
"""
图片内容倾向分析（简化版）
基于色彩 / 亮度 / 饱和度 / 对比度等特征，输出一个"压抑指数"与倾向描述。

注意：这是基于像素特征的简化分析，不包含对画面内容的语义理解
（真正的"看懂图片内容"需要视觉大模型，可作为后续升级项）。
图片中有文字时，请以 OCR 提取文字后的情感分析结果为准。
"""
import numpy as np
from PIL import Image


def analyze(image_path):
    """分析一张图片的色彩/亮度倾向。

    返回 dict：
      brightness      平均亮度 0~255
      saturation      平均饱和度 0~1
      warmth          冷暖（正=偏暖，负=偏冷）
      contrast        对比度（标准差）
      pressure_index  压抑指数 0~100（纯启发式）
      description     倾向描述
      note            分析方式说明
    """
    try:
        img = Image.open(image_path).convert("RGB")
        img = img.resize((64, 64))
        arr = np.asarray(img, dtype=np.float32)          # (64,64,3)
        r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]

        brightness = float(arr.mean())                    # 0~255
        saturation = float((arr.max(axis=2) - arr.min(axis=2)).mean()) / 255.0
        warmth = float((r.mean() - b.mean())) / 255.0     # 正=偏暖
        contrast = float(arr.std())

        dark = brightness < 90
        gloomy = dark and saturation < 0.18

        # 压抑指数 0~100（启发式打分）
        pressure = 100.0
        pressure -= min(brightness, 255) / 255.0 * 55     # 越亮越减压
        pressure -= saturation * 30                       # 彩色减压
        pressure -= max(0.0, warmth) * 15                 # 暖色减压
        if contrast < 25:
            pressure += 10                                # 画面平淡更压抑
        # 亮而素净（白底文档/纯色图）→ 视为中性，压低指数，不判为压抑
        if brightness > 200 and saturation < 0.12:
            pressure = min(pressure, 35.0)
        pressure = max(0, min(100, int(round(pressure))))

        if gloomy:
            desc = "画面暗沉、色彩偏灰，整体给人压抑/低落的感觉"
        elif dark:
            desc = "画面偏暗，氛围比较沉重"
        elif brightness > 190 and saturation > 0.35:
            desc = "画面明亮、色彩鲜艳，整体轻松活泼"
        elif brightness > 170:
            desc = "画面明亮，氛围偏积极"
        elif warmth < -0.05:
            desc = "画面偏冷色调，氛围偏冷静/严肃"
        else:
            desc = "画面色彩与明暗较为均衡，倾向不明显"

        return {
            "brightness": int(brightness),
            "saturation": round(saturation, 2),
            "warmth": round(warmth, 2),
            "contrast": int(contrast),
            "pressure_index": pressure,
            "description": desc,
            "note": "此为基于色彩/亮度的简化特征分析，不含语义内容理解",
        }
    except Exception as e:  # noqa: BLE001
        return {
            "error": "图片分析失败：%s" % e,
            "pressure_index": None,
            "description": "图片分析失败",
        }
