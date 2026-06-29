from pathlib import Path
from typing import Literal


class DocumentSplitter:
    """统一的文档加载 + 分割器"""
    def __init__(self,
        chunk_size: int = 800,
        chunk_overlap: int = 100,
        strategy:Literal["recursive", "char", "sentence"] = "recursive"
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.strategy = strategy
        self._separators = ["\n\n", "\n", "。", "；", "，", ". ", " ", ""]
        pass


    def load(self, file_path: str) -> list[dict]:
        """根据扩展名自动选加载器，返回 list[page]"""
        ext = Path(file_path).suffix.lower()

        if ext == ".pdf":
            return self._load_pdf(file_path)
        elif ext in (".md", ".txt", ".html"):
            pages = self._load_text(file_path)
            return [pages]
        else:
            raise ValueError(f"不支持的文件类型: {ext}") 

    def _load_pdf(self, file_path: str) -> list[dict]:
        try:
            import pymupdf
        except ImportError:
            try:
                import fitz as pymupdf
            except ImportError:
                raise ImportError(
                    "PDF 解析需要 pymupdf（pip install pymupdf）或 fitz（pip install pymupdf）"
                )
        pages = []
        doc = pymupdf.open(file_path)
        for i, page in enumerate(doc):
            text = page.get_text()
            if text.strip():
                pages.append({
                    "page": i + 1,
                    "text": text,
                    "metadata": {"source": Path(file_path).name, "page": i + 1},
                })
        doc.close()
        return pages
    
    def _load_text(self, file_path: str) -> dict:
        with open(file_path, "r", encoding= "utf-8") as f:
            text = f.read();
        return { "text": text, "metadata": {"source": Path(file_path).name}}
    
    def split(self, file_path: str) -> list[dict]:
        """加载 + 分割，返回 list[chunk]"""
        pages = self.load(file_path)
        all_chunks = []
        for page in pages:
            if self.strategy == "recursive":
                chunks = self._split_recursive(page["text"])
            elif self.strategy == "char":
                chunks = self._split_by_char(page["text"])
            elif self.strategy == "sentence":
                chunks = self._split_by_sentence(page["text"])
            else:
                raise ValueError(f"未知策略: {self.strategy}")
            
            # 把 page 的 metadata 合并到每个 chunk
            for c in chunks:
                c["metadata"] = {**page.get("metadata", {}), **c.get("metadata", {})}

            all_chunks.extend(chunks)

        return all_chunks


    def _is_heading(self, text: str) -> bool:
        """检测文本是否为 Markdown 或 RST 标题"""
        import re
        text = text.strip()
        # Markdown 标题: # 标题
        if re.match(r'^#{1,6}\s', text):
            return True
        # RST/TXT 标题下划线: 标题\n---
        lines = text.split('\n')
        if len(lines) >= 2 and len(lines[0]) < 100:
            underline = lines[1].strip()
            if underline and all(c in '-=~' for c in underline):
                return True
        return False

    def _merge_heading_chunks(self, chunks: list[dict]) -> list[dict]:
        """合并标题 chunk 和下一个内容 chunk，确保标题不单独成块"""
        if not chunks:
            return chunks
        merged = []
        i = 0
        max_len = int(self.chunk_size * 1.5)
        while i < len(chunks):
            chunk = chunks[i]
            text = chunk["text"].strip()
            if self._is_heading(text) and i + 1 < len(chunks):
                next_text = chunks[i + 1]["text"].strip()
                combined = text + "\n\n" + next_text
                if len(combined) <= max_len:
                    merged.append({"text": combined})
                    i += 2
                    continue
                else:
                    # 超过限制也要合并标题+部分内容，剩余内容保留
                    avail = max_len - len(text) - 2
                    if avail > 50:
                        merged.append({"text": text + "\n\n" + next_text[:avail]})
                        remain = next_text[avail:].strip()
                        if remain:
                            chunks[i + 1] = {"text": remain}
                            merged.append(chunks[i + 1])
                        i += 2
                        continue
            merged.append(chunk)
            i += 1
        return merged

    def _split_recursive(self, text: str)  -> list[dict]:
        """递归字符分割"""
        if len(text) < self.chunk_size:
            return [{"text": text}] if text.strip() else []
        
        sep = self._separators[0]
        if sep == "":
            return self._split_by_char(text)
        
        chunks = []
        for part in text.split(sep):
            if not part.strip():
                continue
            if len(part) <= self.chunk_size:
                chunks.append({"text": part})
            else:
                # 用剩余分隔符递归切
                saved = self._separators
                self._separators = self._separators[1:]
                chunks.extend(self._split_recursive(part))
                self._separators = saved  # 恢复
        
        # 标题合并：确保标题和后续内容在同一个 chunk
        chunks = self._merge_heading_chunks(chunks)
        return chunks

    def _split_by_char(self, text: str) -> list[dict]:
        chunks = []
        step = self.chunk_size - self.chunk_overlap
        for i in range(0, len(text), step):
            chunk_text = text[i:i + self.chunk_size]
            if chunk_text.strip():
                chunks.append({"text": chunk_text})
        return chunks
    
    def _split_by_sentence(self, text: str) -> list[dict]:
        import re
        sentences = re.split(r"(?<=[。！？.!?\n])\s*", text)
        chunks = []
        current = ""
        for sent in sentences:
            if len(current) + len(sent) <= self.chunk_size:
                current += sent
            else:
                if current.strip():
                    chunks.append({"text": current})
                current = sent
        if current.strip():
            chunks.append({"text": current})
        return chunks