#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
知识库管理器：整合PDF解析、文本分块、向量化、FAISS存储、语义检索
支持本地sentence-transformers和OpenAI Embedding API两种向量化方式
"""

import os
import json
import pickle
import hashlib
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import numpy as np

from .pdf_parser import PDFParser


class KnowledgeBase:
    """简历素材知识库"""

    def __init__(self, data_dir="./data", config=None):
        """
        Args:
            data_dir: 数据存储目录
            config: 配置字典（可选，默认从config.yaml读取）
        """
        self.data_dir = Path(data_dir)
        self.pdf_dir = self.data_dir / "pdfs"
        self.chunk_dir = self.data_dir / "chunks"
        self.index_dir = self.data_dir / "faiss_index"

        for d in [self.data_dir, self.pdf_dir, self.chunk_dir, self.index_dir]:
            d.mkdir(parents=True, exist_ok=True)

        # 配置
        self.config = config or {}
        kb_config = self.config.get("knowledge_base", {})
        self.chunk_size = kb_config.get("chunk_size", 500)
        self.chunk_overlap = kb_config.get("chunk_overlap", 50)
        self.top_k = kb_config.get("top_k", 8)
        self.score_threshold = kb_config.get("score_threshold", 0.3)

        emb_config = self.config.get("embedding", {})
        self.emb_type = emb_config.get("type", "local")
        self.emb_local_model = emb_config.get("local_model", "paraphrase-multilingual-MiniLM-L12-v2")

        # 状态
        self._embedder = None
        self._index = None
        self._use_faiss = True  # FAISS不可用时回退到numpy
        self._chunks = []  # [{id, text, source, page, metadata}]
        self._doc_hashes = {}  # {filename: hash} 用于检测文件变更

        # 加载已有索引
        self._load()

    # ============================================================
    # PDF 添加与解析
    # ============================================================
    def add_pdf(self, pdf_path: str, rebuild_index: bool = True) -> Dict:
        """
        添加单个PDF到知识库

        Args:
            pdf_path: PDF文件路径
            rebuild_index: 是否立即重建索引

        Returns:
            dict: 处理结果
        """
        pdf_path = str(Path(pdf_path).resolve())
        filename = os.path.basename(pdf_path)

        # 计算文件哈希，检测是否已处理且未变更
        file_hash = self._compute_file_hash(pdf_path)
        if filename in self._doc_hashes and self._doc_hashes[filename] == file_hash:
            print(f"[跳过] {filename} 已存在且未变更")
            return {"status": "skipped", "filename": filename}

        # 解析PDF
        print(f"[解析] {filename}")
        parser = PDFParser(backend="pymupdf")
        result = parser.parse(pdf_path)

        # 分块
        chunks = self._chunk_text(result)
        print(f"  生成 {len(chunks)} 个文本块")

        # 移除该文件的旧chunk
        self._chunks = [c for c in self._chunks if c.get("source") != filename]

        # 添加新chunk
        self._chunks.extend(chunks)
        self._doc_hashes[filename] = file_hash

        # 保存chunk数据
        self._save_chunks()

        # 重建索引
        if rebuild_index:
            self.build_index()

        return {
            "status": "added",
            "filename": filename,
            "page_count": result["page_count"],
            "chunk_count": len(chunks)
        }

    def add_pdf_directory(self, dir_path: str) -> List[Dict]:
        """
        批量添加目录下所有PDF

        Args:
            dir_path: PDF目录路径

        Returns:
            list[dict]: 每个PDF的处理结果
        """
        dir_path = Path(dir_path)
        pdf_files = sorted(list(dir_path.glob("*.pdf")) + list(dir_path.glob("*.PDF")))
        print(f"找到 {len(pdf_files)} 个PDF文件")

        results = []
        for pdf_file in pdf_files:
            result = self.add_pdf(str(pdf_file), rebuild_index=False)
            results.append(result)

        # 全部添加完后重建一次索引
        if any(r["status"] == "added" for r in results):
            self.build_index()

        return results

    def remove_pdf(self, filename: str) -> bool:
        """
        从知识库中移除PDF

        Args:
            filename: 文件名

        Returns:
            bool: 是否成功移除
        """
        original_count = len(self._chunks)
        self._chunks = [c for c in self._chunks if c.get("source") != filename]
        self._doc_hashes.pop(filename, None)

        if len(self._chunks) < original_count:
            self._save_chunks()
            self.build_index()
            print(f"[移除] {filename}，删除 {original_count - len(self._chunks)} 个文本块")
            return True
        else:
            print(f"[未找到] {filename}")
            return False

    # ============================================================
    # 文本分块
    # ============================================================
    def _chunk_text(self, pdf_result: Dict) -> List[Dict]:
        """
        将PDF解析结果分块

        优先按经历点/段落分割，不足时按字符数分割
        """
        chunks = []
        filename = pdf_result["filename"]
        full_text = pdf_result["full_text"]

        # 策略1：按空行分割成段落，然后合并小段落
        paragraphs = [p.strip() for p in full_text.split("\n\n") if p.strip()]

        current_chunk = ""
        chunk_id = 0

        for para in paragraphs:
            # 如果当前块 + 新段落超过chunk_size，先保存当前块
            if current_chunk and len(current_chunk) + len(para) > self.chunk_size:
                chunks.append(self._make_chunk(chunk_id, current_chunk, filename, pdf_result))
                chunk_id += 1
                # 保留overlap
                if self.chunk_overlap > 0:
                    current_chunk = current_chunk[-self.chunk_overlap:] + "\n\n" + para
                else:
                    current_chunk = para
            else:
                if current_chunk:
                    current_chunk += "\n\n" + para
                else:
                    current_chunk = para

        # 处理最后一个块
        if current_chunk.strip():
            chunks.append(self._make_chunk(chunk_id, current_chunk, filename, pdf_result))

        return chunks

    def _make_chunk(self, chunk_id: int, text: str, filename: str, pdf_result: Dict) -> Dict:
        """创建一个chunk字典"""
        return {
            "id": f"{filename}#{chunk_id}",
            "text": text.strip(),
            "source": filename,
            "page_count": pdf_result.get("page_count", 0),
            "char_count": len(text.strip())
        }

    # ============================================================
    # 向量化
    # ============================================================
    def _get_embedder(self):
        """获取向量化模型（懒加载）"""
        if self._embedder is not None:
            return self._embedder

        if self.emb_type == "local":
            try:
                # 本地模型离线加载（防止访问huggingface被墙卡住）
                os.environ.setdefault("HF_HUB_OFFLINE", "1")
                os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
                from sentence_transformers import SentenceTransformer
                print(f"[加载] 本地Embedding模型: {self.emb_local_model}")
                # 支持本地路径加载；若配置是模型名则先检查本地缓存
                model_path = self.emb_local_model
                if model_path and not os.path.isabs(model_path):
                    local_cache = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models", model_path)
                    if os.path.isdir(local_cache):
                        model_path = local_cache
                self._embedder = SentenceTransformer(model_path)
            except ImportError:
                print("[提示] sentence-transformers 未安装，自动回退到TF-IDF向量化")
                self.emb_type = "tfidf"
                self._embedder = TfidfEmbedder()
        elif self.emb_type == "tfidf":
            self._embedder = TfidfEmbedder()
        elif self.emb_type == "openai":
            self._embedder = OpenAIEmbedder(self.config.get("embedding", {}).get("openai", {}))
        else:
            raise ValueError(f"不支持的embedding类型: {self.emb_type}")

        return self._embedder

    def _embed_texts(self, texts: List[str]) -> np.ndarray:
        """批量向量化文本"""
        embedder = self._get_embedder()
        if self.emb_type == "local":
            embeddings = embedder.encode(texts, show_progress_bar=True, normalize_embeddings=True)
            return np.array(embeddings, dtype=np.float32)
        elif self.emb_type == "tfidf":
            return embedder.encode(texts, fit=not getattr(self, '_tfidf_fitted', False))
        else:
            return embedder.encode(texts)

    def _embed_query(self, text: str) -> np.ndarray:
        """向量化查询文本"""
        return self._embed_texts([text])[0]

    # ============================================================
    # FAISS 索引构建与检索
    # ============================================================
    def build_index(self) -> bool:
        """
        构建FAISS向量索引

        Returns:
            bool: 是否成功构建
        """
        if not self._chunks:
            print("[警告] 没有文本块，无法构建索引")
            return False

        print(f"[构建索引] {len(self._chunks)} 个文本块")
        texts = [c["text"] for c in self._chunks]
        embeddings = self._embed_texts(texts)

        # 标记TF-IDF已fit（查询时不再重新fit）
        if self.emb_type == "tfidf":
            self._tfidf_fitted = True

        # 尝试使用FAISS，不可用时回退到numpy
        try:
            import faiss
            dimension = embeddings.shape[1]
            self._index = faiss.IndexFlatIP(dimension)
            self._index.add(embeddings)
            self._use_faiss = True
            print(f"[完成] FAISS索引: 维度={dimension}, 向量数={self._index.ntotal}")
        except ImportError:
            print("[提示] faiss-cpu 未安装，使用numpy回退方案（检索速度稍慢但功能完整）")
            self._index = embeddings  # numpy数组作为索引
            self._use_faiss = False
            print(f"[完成] Numpy索引: 向量数={len(embeddings)}, 维度={embeddings.shape[1]}")

        # 保存索引
        self._save_index()
        return True

    def search(self, query: str, top_k: Optional[int] = None, score_threshold: Optional[float] = None) -> List[Dict]:
        """
        语义检索

        Args:
            query: 查询文本（如JD描述、岗位关键词）
            top_k: 返回结果数量，默认使用配置值
            score_threshold: 相似度阈值，默认使用配置值

        Returns:
            list[dict]: [{id, text, source, score, rank}, ...]
        """
        if self._index is None:
            print("[警告] 索引未构建或为空，请先添加PDF并构建索引")
            return []

        # 检查索引是否有数据
        if getattr(self, '_use_faiss', True):
            if self._index.ntotal == 0:
                print("[警告] 索引为空")
                return []
        else:
            if len(self._index) == 0:
                print("[警告] 索引为空")
                return []

        top_k = top_k or self.top_k
        score_threshold = score_threshold if score_threshold is not None else self.score_threshold

        # 向量化查询
        query_emb = self._embed_query(query).reshape(1, -1)

        # 检索
        if getattr(self, '_use_faiss', True):
            # FAISS检索
            scores, indices = self._index.search(query_emb, min(top_k * 2, self._index.ntotal))
            scored_indices = list(zip(scores[0], indices[0]))
        else:
            # Numpy回退：计算余弦相似度（embedding已归一化，内积=余弦相似度）
            similarities = np.dot(self._index, query_emb[0])
            # 排序并取top_k*2
            sorted_indices = np.argsort(similarities)[::-1][:top_k * 2]
            scored_indices = [(float(similarities[i]), int(i)) for i in sorted_indices]

        results = []
        rank = 1
        for score, idx in scored_indices:
            if idx < 0 or idx >= len(self._chunks):
                continue
            if score < score_threshold:
                continue
            chunk = self._chunks[idx]
            results.append({
                "id": chunk["id"],
                "text": chunk["text"],
                "source": chunk["source"],
                "score": round(score, 4),
                "rank": rank
            })
            rank += 1
            if len(results) >= top_k:
                break

        return results

    # ============================================================
    # 持久化
    # ============================================================
    def _save_chunks(self):
        """保存chunk数据"""
        chunk_file = self.chunk_dir / "chunks.json"
        with open(chunk_file, 'w', encoding='utf-8') as f:
            json.dump({
                "chunks": self._chunks,
                "doc_hashes": self._doc_hashes
            }, f, ensure_ascii=False, indent=2)

    def _save_index(self):
        """保存向量索引（FAISS或Numpy）"""
        if self._index is None:
            return
        try:
            if getattr(self, '_use_faiss', True):
                import faiss
                import os as _os
                index_file = self.index_dir / "index.faiss"
                # faiss在Windows下无法打开含中文的绝对路径，切换到索引目录后用相对文件名写入
                _old_cwd = _os.getcwd()
                _os.chdir(str(self.index_dir))
                try:
                    faiss.write_index(self._index, "index.faiss")
                finally:
                    _os.chdir(_old_cwd)
            else:
                # Numpy格式保存
                index_file = self.index_dir / "index.npy"
                np.save(str(index_file), self._index)
            # 保存后端类型标记
            meta_file = self.index_dir / "index_meta.json"
            meta = {"use_faiss": getattr(self, '_use_faiss', True)}
            # 如果是TF-IDF，同时保存词汇表和IDF
            if self.emb_type == "tfidf" and self._embedder is not None:
                meta["tfidf_vocab"] = self._embedder.vocab
                meta["tfidf_idf"] = self._embedder.idf.tolist()
            with open(meta_file, 'w', encoding='utf-8') as f:
                json.dump(meta, f, ensure_ascii=False)
        except Exception as e:
            print(f"[警告] 保存索引失败: {e}")

    def _load(self):
        """加载已有索引和chunk数据"""
        chunk_file = self.chunk_dir / "chunks.json"
        if chunk_file.exists():
            try:
                with open(chunk_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self._chunks = data.get("chunks", [])
                    self._doc_hashes = data.get("doc_hashes", {})
            except Exception as e:
                print(f"[警告] 加载chunk数据失败: {e}")

        # 加载索引元信息（判断后端类型）
        meta_file = self.index_dir / "index_meta.json"
        use_faiss = True
        if meta_file.exists():
            try:
                with open(meta_file, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
                    use_faiss = meta.get("use_faiss", True)
            except Exception:
                pass

        if use_faiss:
            index_file = self.index_dir / "index.faiss"
            if index_file.exists() and self._chunks:
                try:
                    import faiss
                    import os as _os
                    _old_cwd = _os.getcwd()
                    _os.chdir(str(self.index_dir))
                    try:
                        self._index = faiss.read_index("index.faiss")
                    finally:
                        _os.chdir(_old_cwd)
                    self._use_faiss = True
                    print(f"[加载] 已有FAISS索引: {self._index.ntotal} 个向量, {len(self._chunks)} 个文本块")
                except Exception as e:
                    print(f"[警告] 加载FAISS索引失败: {e}，将使用numpy回退")
                    self._index = None
        else:
            index_file = self.index_dir / "index.npy"
            if index_file.exists() and self._chunks:
                try:
                    self._index = np.load(str(index_file))
                    self._use_faiss = False
                    # 恢复TF-IDF词汇表
                    if "tfidf_vocab" in meta:
                        self.emb_type = "tfidf"
                        self._embedder = TfidfEmbedder()
                        self._embedder.vocab = meta["tfidf_vocab"]
                        self._embedder.idf = np.array(meta["tfidf_idf"], dtype=np.float32)
                        self._embedder._fitted = True
                        self._tfidf_fitted = True
                    print(f"[加载] 已有Numpy索引: {len(self._index)} 个向量, {len(self._chunks)} 个文本块")
                except Exception as e:
                    print(f"[警告] 加载Numpy索引失败: {e}")
                    self._index = None

    # ============================================================
    # 工具方法
    # ============================================================
    @staticmethod
    def _compute_file_hash(filepath: str) -> str:
        """计算文件MD5哈希"""
        hash_md5 = hashlib.md5()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()

    def stats(self) -> Dict:
        """返回知识库统计信息"""
        index_size = 0
        if self._index is not None:
            if getattr(self, '_use_faiss', True):
                index_size = self._index.ntotal
            else:
                index_size = len(self._index)
        return {
            "total_chunks": len(self._chunks),
            "total_documents": len(self._doc_hashes),
            "documents": list(self._doc_hashes.keys()),
            "index_built": self._index is not None and index_size > 0,
            "index_size": index_size,
            "embedding_type": self.emb_type,
            "chunk_size": self.chunk_size,
            "top_k": self.top_k
        }

    def list_documents(self) -> List[str]:
        """列出已添加的文档"""
        return list(self._doc_hashes.keys())

    def clear(self):
        """清空知识库"""
        self._chunks = []
        self._doc_hashes = {}
        self._index = None
        # 删除文件
        chunk_file = self.chunk_dir / "chunks.json"
        index_file = self.index_dir / "index.faiss"
        for f in [chunk_file, index_file]:
            if f.exists():
                f.unlink()
        print("[清空] 知识库已清空")


class TfidfEmbedder:
    """TF-IDF向量化器（纯numpy实现，零额外依赖，轻量回退方案）"""

    def __init__(self, ngram_range=(2, 4), max_features=10000):
        self.ngram_range = ngram_range
        self.max_features = max_features
        self.vocab = {}  # {ngram: index}
        self.idf = None  # 逆文档频率
        self._fitted = False

    def _extract_ngrams(self, text: str) -> List[str]:
        """从文本中提取字符级n-gram"""
        text = text.lower()
        ngrams = []
        for n in range(self.ngram_range[0], self.ngram_range[1] + 1):
            for i in range(len(text) - n + 1):
                ngrams.append(text[i:i+n])
        return ngrams

    def _build_vocab(self, texts: List[str]):
        """构建词汇表，按文档频率排序取top-k"""
        doc_freq = {}
        for text in texts:
            ngrams = set(self._extract_ngrams(text))
            for ng in ngrams:
                doc_freq[ng] = doc_freq.get(ng, 0) + 1

        # 按文档频率排序，取top-k
        sorted_ngrams = sorted(doc_freq.items(), key=lambda x: x[1], reverse=True)
        sorted_ngrams = sorted_ngrams[:self.max_features]
        self.vocab = {ng: idx for idx, (ng, _) in enumerate(sorted_ngrams)}

        # 计算IDF
        n_docs = len(texts)
        self.idf = np.zeros(len(self.vocab), dtype=np.float32)
        for ng, idx in self.vocab.items():
            df = doc_freq[ng]
            # 平滑IDF: log((1+n_docs) / (1+df)) + 1
            self.idf[idx] = np.log((1 + n_docs) / (1 + df)) + 1

    def encode(self, texts: List[str], fit: bool = False) -> np.ndarray:
        """
        向量化文本

        Args:
            texts: 文本列表
            fit: 是否fit（首次构建索引时为True，查询时为False）

        Returns:
            np.ndarray: L2归一化的稠密向量
        """
        if fit or not self._fitted:
            self._build_vocab(texts)
            self._fitted = True

        if not self.vocab:
            return np.zeros((len(texts), 1), dtype=np.float32)

        vocab_size = len(self.vocab)
        tfidf_matrix = np.zeros((len(texts), vocab_size), dtype=np.float32)

        for doc_idx, text in enumerate(texts):
            ngrams = self._extract_ngrams(text)
            if not ngrams:
                continue
            # 计算词频
            tf = {}
            for ng in ngrams:
                if ng in self.vocab:
                    tf[ng] = tf.get(ng, 0) + 1
            # 归一化TF（除以总词数）
            total = len(ngrams)
            for ng, count in tf.items():
                idx = self.vocab[ng]
                tfidf_matrix[doc_idx, idx] = (count / total) * self.idf[idx]

        # L2归一化
        norms = np.linalg.norm(tfidf_matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0  # 避免除零
        tfidf_matrix = tfidf_matrix / norms

        return tfidf_matrix


class OpenAIEmbedder:
    """OpenAI兼容API的Embedding客户端"""

    def __init__(self, config: Dict):
        self.api_key = config.get("api_key", "")
        self.base_url = config.get("base_url", "https://api.openai.com/v1")
        self.model = config.get("model", "text-embedding-3-small")
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                from openai import OpenAI
                self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)
            except ImportError:
                raise ImportError("openai 库未安装。请运行: pip install openai")
        return self._client

    def encode(self, texts: List[str]) -> np.ndarray:
        """批量编码"""
        client = self._get_client()
        # 分批处理（API限制）
        batch_size = 64
        all_embeddings = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            response = client.embeddings.create(input=batch, model=self.model)
            batch_embeddings = [item.embedding for item in response.data]
            all_embeddings.extend(batch_embeddings)
            print(f"  已编码 {min(i + batch_size, len(texts))}/{len(texts)}")

        # 归一化
        embeddings = np.array(all_embeddings, dtype=np.float32)
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        embeddings = embeddings / norms
        return embeddings
