# -*- coding: utf-8 -*-
"""
生成用于测试的图片（含中文文字的图片 + 明暗风格图）。
用法：C:\\Python3\\python.exe make_test_images.py
生成到 test_images\\ 目录。
"""
import os

from PIL import Image, ImageDraw, ImageFont

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",    # 微软雅黑
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\simsun.ttc",  # 宋体
    r"C:\Windows\Fonts\simhei.ttf",  # 黑体
]


def get_font(size):
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def make_text_image(path, text, bg=(255, 255, 255), fg=(0, 0, 0), size=(800, 300)):
    img = Image.new("RGB", size, bg)
    d = ImageDraw.Draw(img)
    font = get_font(40)
    y = 60
    for line in text.split("\n"):
        d.text((60, y), line, fill=fg, font=font)
        y += 70
    img.save(path)
    print("生成：", path)


def main():
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_images")
    os.makedirs(out, exist_ok=True)

    # 1) 含负面文字的图片
    make_text_image(
        os.path.join(out, "test_negative.png"),
        "该员工经常迟到早退\n消极怠工 收到客户多次投诉",
    )
    # 2) 含正面文字的图片
    make_text_image(
        os.path.join(out, "test_positive.png"),
        "该员工工作积极认真负责\n客户满意度高 获得多次表扬",
    )
    # 3) 暗沉风格图（无文字）
    img = Image.new("RGB", (800, 500), (35, 35, 42))
    d = ImageDraw.Draw(img)
    for i in range(220):
        d.point((i * 4, i % 500), fill=(18, 18, 24))
    img.save(os.path.join(out, "test_dark.png"))
    print("生成：", os.path.join(out, "test_dark.png"))
    # 4) 明亮风格图（无文字）
    img = Image.new("RGB", (800, 500), (255, 214, 90))
    d = ImageDraw.Draw(img)
    for i in range(120):
        x = (i * 7) % 800
        y = (i * 13) % 460
        d.ellipse((x, y, x + 44, y + 44), fill=(66, 183, 133))
    img.save(os.path.join(out, "test_bright.png"))
    print("生成：", os.path.join(out, "test_bright.png"))

    print("\n完成！打开网页 http://127.0.0.1:5000 上传 test_images 目录里的图片即可测试。")


if __name__ == "__main__":
    main()
