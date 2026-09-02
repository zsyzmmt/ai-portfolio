# -*- coding: utf-8 -*-
"""
云鉴 · 屏幕截图分析工具
========================
在屏幕任意区域框选文字（QQ空间 / 朋友圈 / 聊天记录等），
自动 OCR 识别 + 合规分析，结果在浏览器中展示。

依赖：tkinter（Python 自带）+ Pillow（已装）+ requests（已装）
启动：双击「启动截图分析.bat」
"""
import io
import os
import sys
import tempfile
import webbrowser
from tkinter import Tk, Toplevel, Canvas, Label, Frame, BOTH, YES, LEFT

import requests
from PIL import ImageGrab

# ---- 配置 ----
API_URL = "http://127.0.0.1:5000/quick-capture"
FONT = ("Microsoft YaHei", 11)
BANNER_TEXT = "📷 框选屏幕文字分析"

COLOR_BG = "#F7F9FC"
COLOR_NAVY = "#0F1B3D"
COLOR_GOLD = "#E8C877"
COLOR_INK = "#1A2233"
COLOR_SLATE = "#4A5568"
COLOR_WHITE = "#FFFFFF"


class SnipTool:
    def __init__(self):
        self.root = Tk()
        self.root.title("")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)

        # 浮动按钮
        self.banner = Frame(self.root, bg=COLOR_NAVY, cursor="cross")
        self.banner.pack(fill=BOTH, expand=YES)

        self.lbl = Label(
            self.banner,
            text=BANNER_TEXT,
            font=("Microsoft YaHei", 12, "bold"),
            fg=COLOR_GOLD,
            bg=COLOR_NAVY,
            padx=16,
            pady=10,
        )
        self.lbl.pack()

        # 绑定点击事件
        self.lbl.bind("<Button-1>", self.start_snip)
        self.lbl.bind("<Button-3>", self.close_app)
        self.lbl.bind("<Enter>", lambda e: self.lbl.configure(bg="#162852"))
        self.lbl.bind("<Leave>", lambda e: self.lbl.configure(bg=COLOR_NAVY))

        # 拖拽窗口
        self.lbl.bind("<B1-Motion>", self._drag)
        self._drag_x = 0
        self._drag_y = 0

        # 放在右下角
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry("220x44+%d+%d" % (sw - 250, sh - 90))

        # ESC 关闭
        self.root.bind("<Escape>", lambda e: self.close_app(None))

        # 选区覆盖层引用
        self.overlay = None
        self.canvas = None
        self.start_x = 0
        self.start_y = 0
        self.rect_id = None

    # ----- 浮动窗口拖拽 -----
    def _drag(self, event):
        x = self.root.winfo_x() + (event.x - self._drag_x)
        y = self.root.winfo_y() + (event.y - self._drag_y)
        self.root.geometry("+%d+%d" % (x, y))

    def _drag_start(self, event):
        self._drag_x = event.x
        self._drag_y = event.y
        self.lbl.bind("<Button-1>", self.start_snip)

    def bind_drag(self):
        self.lbl.bind("<Button-1>", None)
        self.lbl.bind("<ButtonPress-1>", self._drag_start, add="+")
        self.lbl.bind("<Button-1>", self.start_snip, add="+")

    # ----- 开始框选 -----
    def start_snip(self, event=None):
        self.root.withdraw()
        self.root.update_idletasks()
        self.root.after(200, self._show_overlay)

    def _show_overlay(self):
        self.overlay = Toplevel(self.root)
        self.overlay.attributes("-fullscreen", True)
        self.overlay.attributes("-topmost", True)
        self.overlay.attributes("-alpha", 0.28)
        self.overlay.configure(bg="black")
        self.overlay.bind("<Escape>", self._cancel_snip)

        self.canvas = Canvas(self.overlay, bg="black", highlightthickness=0)
        self.canvas.pack(fill=BOTH, expand=YES)

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)

        # 提示文字
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.hint = self.canvas.create_text(
            sw // 2, sh // 2,
            text="拖动鼠标框选要分析的屏幕文字区域\n按 Esc 取消",
            fill="#E8C877",
            font=("Microsoft YaHei", 15, "bold"),
            justify="center",
        )

    def _cancel_snip(self, event=None):
        if self.overlay:
            self.overlay.destroy()
        self.overlay = None
        self.canvas = None
        self.root.deiconify()

    def _on_press(self, event):
        self.start_x = event.x
        self.start_y = event.y
        if hasattr(self, "hint") and self.hint:
            self.canvas.delete(self.hint)
            self.hint = None
        self.rect_id = self.canvas.create_rectangle(
            event.x, event.y, event.x, event.y,
            outline="#E8C877", width=2, dash=(8, 4),
        )

    def _on_drag(self, event):
        self.canvas.coords(self.rect_id, self.start_x, self.start_y, event.x, event.y)

    def _on_release(self, event):
        x1 = min(self.start_x, event.x)
        y1 = min(self.start_y, event.y)
        x2 = max(self.start_x, event.x)
        y2 = max(self.start_y, event.y)

        self.overlay.destroy()
        self.overlay = None
        self.canvas = None

        w, h = x2 - x1, y2 - y1
        if w < 15 or h < 15:
            self._show_error("选区太小（至少 15×15 像素），请重新框选。")
            self.root.deiconify()
            return

        try:
            img = ImageGrab.grab(bbox=(x1, y1, x2, y2), all_screens=True)
        except Exception as e:
            self._show_error("截图失败：%s" % str(e))
            self.root.deiconify()
            return

        self._analyze(img)

    # ----- 发送分析 -----
    def _analyze(self, img):
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)

        try:
            resp = requests.post(
                API_URL,
                files={"image": ("snip.png", buf, "image/png")},
                timeout=30,
            )
        except requests.exceptions.ConnectionError:
            self._show_error("无法连接分析服务。\n\n请先双击「启动.bat」启动网页服务，再运行截图工具。")
            self.root.deiconify()
            return
        except Exception as e:
            self._show_error("分析请求失败：%s" % str(e))
            self.root.deiconify()
            return

        if resp.status_code != 200:
            self._show_error("分析服务返回错误（%d），请稍后重试。" % resp.status_code)
            self.root.deiconify()
            return

        # 保存 HTML 结果到临时文件并打开浏览器
        try:
            fd, path = tempfile.mkstemp(suffix=".html", prefix="capture_result_")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(resp.text)
            webbrowser.open("file://" + path)
        except Exception as e:
            self._show_error("显示结果失败：%s" % str(e))

        self.root.deiconify()

    # ----- 错误提示 -----
    def _show_error(self, msg):
        top = Toplevel(self.root)
        top.title("云鉴 · 提示")
        top.configure(bg=COLOR_BG)
        top.resizable(False, False)
        top.attributes("-topmost", True)
        x = self.root.winfo_x() - 100
        y = self.root.winfo_y() - 120
        top.geometry("320x140+%d+%d" % (max(0, x), max(0, y)))

        Label(
            top, text=msg, font=FONT, fg=COLOR_SLATE, bg=COLOR_BG,
            justify="left", wraplength=280, padx=20, pady=16,
        ).pack()

        btn = Label(
            top, text="知道了", font=("Microsoft YaHei", 11, "bold"),
            fg=COLOR_WHITE, bg=COLOR_NAVY, padx=24, pady=7, cursor="hand2",
        )
        btn.pack(pady=(0, 14))
        btn.bind("<Button-1>", lambda e: top.destroy())

    # ----- 关闭 -----
    def close_app(self, event=None):
        self.root.destroy()

    def run(self):
        self.bind_drag()
        self.root.mainloop()


if __name__ == "__main__":
    SnipTool().run()
