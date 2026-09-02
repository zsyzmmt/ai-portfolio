#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PDF解析器：从PDF文件中提取文本内容
支持 PyMuPDF (fitz) 和 pdfplumber 两种后端
"""

import os
from pathlib import Path
from typing import List, Dict, Optional


class PDFParser:
    """PDF文本解析器"""

    def __init__(self, backend="pymupdf"):
        """
        Args:
            backend: 解析后端，可选 "pymupdf" 或 "pdfplumber"
        """
        self.backend = backend
        self._fitz = None
        self._pdfplumber = None

        if backend == "pymupdf":
            try:
                import fitz
                self._fitz = fitz
            except ImportError:
                raise ImportError("PyMuPDF 未安装，请运行: pip install PyMuPDF")
        elif backend == "pdfplumber":
            try:
                import pdfplumber
                self._pdfplumber = pdfplumber
            except ImportError:
                raise ImportError("pdfplumber 未安装，请运行: pip install pdfplumber")
        else:
            raise ValueError(f"不支持的后端: {backend}，可选 pymupdf / pdfplumber")

    def parse(self, pdf_path: str) -> Dict:
        """
        解析PDF文件，提取全文本和按页文本

        Args:
            pdf_path: PDF文件路径

        Returns:
            dict: {
                "path": 文件路径,
                "filename": 文件名,
                "page_count": 页数,
                "full_text": 全文本,
                "pages": [{"page_num": 页码, "text": 该页文本}, ...]
            }
        """
        pdf_path = str(Path(pdf_path).resolve())
        filename = os.path.basename(pdf_path)

        if self.backend == "pymupdf":
            return self._parse_pymupdf(pdf_path, filename)
        else:
            return self._parse_pdfplumber(pdf_path, filename)

    def _parse_pymupdf(self, pdf_path: str, filename: str) -> Dict:
        """使用PyMuPDF解析"""
        doc = self._fitz.open(pdf_path)
        pages = []
        full_text_parts = []

        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text("text")
            text = self._clean_text(text)
            pages.append({
                "page_num": page_num + 1,
                "text": text
            })
            full_text_parts.append(text)

        doc.close()

        return {
            "path": pdf_path,
            "filename": filename,
            "page_count": len(pages),
            "full_text": "\n\n".join(full_text_parts),
            "pages": pages
        }

    def _parse_pdfplumber(self, pdf_path: str, filename: str) -> Dict:
        """使用pdfplumber解析"""
        pages = []
        full_text_parts = []

        with self._pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages):
                text = page.extract_text() or ""
                text = self._clean_text(text)
                pages.append({
                    "page_num": i + 1,
                    "text": text
                })
                full_text_parts.append(text)

        return {
            "path": pdf_path,
            "filename": filename,
            "page_count": len(pages),
            "full_text": "\n\n".join(full_text_parts),
            "pages": pages
        }

    @staticmethod
    def _clean_text(text: str) -> str:
        """清理提取的文本：去除多余空白、修复断行"""
        if not text:
            return ""
        # 替换多种空白字符
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        # 去除行尾空格
        lines = [line.rstrip() for line in text.split("\n")]
        # 合并被错误断开的行（中文行尾没有标点时，可能是断行）
        merged = []
        for i, line in enumerate(lines):
            if not line.strip():
                merged.append("")
                continue
            if merged and merged[-1] and not PDFParser._is_sentence_end(merged[-1]) and not line.startswith((" ", "\t", "•", "-", "*", "1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.")):
                # 可能是断行，合并
                merged[-1] = merged[-1] + line
            else:
                merged.append(line)
        text = "\n".join(merged)
        # 去除多余空行
        while "\n\n\n" in text:
            text = text.replace("\n\n\n", "\n\n")
        return text.strip()

    @staticmethod
    def _is_sentence_end(text: str) -> bool:
        """判断文本是否以句子结束标点结尾"""
        end_chars = ("。", "！", "？", "；", "：", ".", "!", "?", ";", ":", "”", "』", "」", "】", "）", ")")
        return text.rstrip().endswith(end_chars)

    def parse_directory(self, dir_path: str) -> List[Dict]:
        """
        批量解析目录下所有PDF文件

        Args:
            dir_path: 目录路径

        Returns:
            list[dict]: 每个PDF的解析结果
        """
        dir_path = Path(dir_path)
        results = []
        pdf_files = sorted(dir_path.glob("*.pdf")) + sorted(dir_path.glob("*.PDF"))

        print(f"找到 {len(pdf_files)} 个PDF文件")
        for i, pdf_file in enumerate(pdf_files, 1):
            print(f"  [{i}/{len(pdf_files)}] 解析: {pdf_file.name}")
            try:
                result = self.parse(str(pdf_file))
                results.append(result)
                print(f"         页数: {result['page_count']}, 文本长度: {len(result['full_text'])}")
            except Exception as e:
                print(f"         解析失败: {e}")

        return results
