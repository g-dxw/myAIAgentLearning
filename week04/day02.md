# Day 02 — 文档加载 + 文本分割

## 学习目标

掌握加载多种文档格式（PDF/MD/TXT/HTML）的方法，理解分割策略对最终检索质量的决定性影响。

学完今天你能：
1. 用 PyMuPDF 加载 PDF 并逐页提取文本
2. 实现递归字符分割器，按自然边界切分文本
3. 说清楚 chunk_size 和 chunk_overlap 怎么影响检索精度
4. 为不同文档类型选合适的分割参数

---

## 一、为什么需要分割（Chunking）

### 1.1 两个硬约束

```
约束 1: Context Window 有限
  你的 LLM 一次最多读 128K tokens ≈ 一本中篇小说
  你不能把 500 页的 PDF 全塞进 Prompt

约束 2: 检索精度
  一整页 PDF 可能包含 5 个不同话题
  用户只想知道"请假政策"，你却把整页都返回（包含加班、报销等无关内容）
  → 噪声多 → LLM 回答变差
```

### 1.2 分割的目标

```
分割前: [一篇 5000 字的文章，涵盖 4 个主题]
                  ↓
分割后: [chunk_1: 主题 A 的完整段落]
        [chunk_2: 主题 A 的继续]
        [chunk_3: 主题 B 的完整段落]
        [chunk_4: 主题 C + 主题 D 交界（有 overlap）]
        ...

目标: 每个 chunk 语义完整 + 大小适中 + 检索时能精准匹配
```

---

## 二、文档加载器

### 2.1 PDF — PyMuPDF（fitz）

PyMuPDF 是目前最快的 PDF 文本提取库之一。

```bash
pip install pymupdf
```

```python
"""loader_splitter.py — 第一部分：文档加载器"""
import fitz  # PyMuPDF
from pathlib import Path


def load_pdf(file_path: str) -> list[dict]:
    """
    加载 PDF，返回逐页文本。

    返回格式:
    [
        {"page": 1, "text": "第一页的文本内容...", "metadata": {"source": "xxx.pdf"}},
        {"page": 2, "text": "第二页的文本内容...", "metadata": {"source": "xxx.pdf"}},
        ...
    ]
    """
    pages = []
    doc = fitz.open(file_path)

    for i, page in enumerate(doc):
        text = page.get_text()
        if text.strip():  # 跳过空白页
            pages.append({
                "page": i + 1,
                "text": text,
                "metadata": {
                    "source": Path(file_path).name,
                    "page_number": i + 1,
                    "total_pages": len(doc),
                },
            })

    doc.close()
    return pages


def load_markdown(file_path: str) -> dict:
    """加载 Markdown 文件为纯文本"""
    with open(file_path, "r", encoding="utf-8") as f:
        text = f.read()
    return {
        "text": text,
        "metadata": {"source": Path(file_path).name, "type": "markdown"},
    }


def load_text(file_path: str) -> dict:
    """加载纯文本文件"""
    with open(file_path, "r", encoding="utf-8") as f:
        text = f.read()
    return {
        "text": text,
        "metadata": {"source": Path(file_path).name, "type": "text"},
    }
```

### 2.2 文档加载器对照表

| 格式 | 推荐库 | 优点 | 缺点 |
|------|--------|------|------|
| PDF | PyMuPDF (fitz) | 速度快，支持中文 | 扫描版 PDF 需要 OCR |
| PDF（扫描版） | pytesseract | 支持 OCR | 慢，配置复杂 |
| Markdown | 直接 `open()` | 最简单 | — |
| TXT | 直接 `open()` | 最简单 | 需注意编码 |
| HTML | BeautifulSoup | 灵活提取 | 需要写选择器 |
| Word (.docx) | python-docx | 保留格式 | 图片/表格处理复杂 |

---

## 三、四种分割策略

### 3.1 策略一：字符分割（Character Splitter）

最朴素的方式：按固定字符数一刀切。

```python
def split_by_char(text: str, chunk_size: int = 800) -> list[dict]:
    """按固定字符数切分———最简基线"""
    chunks = []
    for i in range(0, len(text), chunk_size):
        chunk_text = text[i:i + chunk_size]
        chunks.append({"text": chunk_text, "start": i, "end": i + len(chunk_text)})
    return chunks
```

**问题：** 完全不考虑语义边界，可能在句子中间切断。

```
原文: "今天我们学习了RAG的原理。RAG是检索增强生成的缩写。"
chunk_size=15:
  chunk_1: "今天我们学习了RAG的原理。"  ← 刚好在句号处
  chunk_2: "RAG是检索增强生成的缩写。"  ← 完整
但:
chunk_size=13:
  chunk_1: "今天我们学习了RAG的"      ← 😱 句子被切断了！
  chunk_2: "原理。RAG是检索增"         ← 😱 更惨
```

### 3.2 策略二：递归字符分割（Recursive Character Splitter）

**这是生产环境最常用的策略。** 思路：按优先级尝试多个分隔符，优先在自然边界处切。

```
优先级从高到低:
  "\n\n"  → 段落边界（最优）
  "\n"    → 行边界
  "。"    → 句子边界（中文）
  "；"    → 分句边界
  "，"    → 短句边界
  " "     → 英文单词边界
  ""      → 兜底：字符级切分

尝试过程:
  1. 用 "\n\n" 切 → 某段还是太长
  2. 对太长的段用 "\n" 切 → 某行还是太长
  3. 对太长的行用 "。" 切 → 某句还是太长
  4. ... 以此类推
  5. 兜底：字符级硬切
```

```python
def split_recursive(
    text: str,
    chunk_size: int = 800,
    chunk_overlap: int = 100,
    separators: list[str] | None = None,
) -> list[dict]:
    """
    递归字符分割器。

    按 separators 优先级依次尝试切分：
    - 先用最高优先级分隔符切
    - 如果某段仍超长，用下一级分隔符对该段继续切
    - 直到所有 chunk 都不超长，或兜底字符级硬切
    """
    if separators is None:
        separators = ["\n\n", "\n", "。", "；", "，", ". ", " ", ""]

    # 递归终止条件：文本本身就不超长
    if len(text) <= chunk_size:
        return [{"text": text}] if text.strip() else []

    # 尝试当前最高优先级分隔符
    sep = separators[0]

    if sep == "":
        # 兜底：字符级硬切
        chunks = []
        for i in range(0, len(text), chunk_size - chunk_overlap):
            chunk_text = text[i:i + chunk_size]
            if chunk_text.strip():
                chunks.append({"text": chunk_text})
        return chunks

    # 用分隔符切分
    parts = text.split(sep)

    # 对于切出来的每一段，如果超长则递归
    chunks = []
    for part in parts:
        if not part.strip():
            continue
        if len(part) <= chunk_size:
            chunks.append({"text": part})
        else:
            # 该段超长，用剩余分隔符递归
            sub_chunks = split_recursive(
                part, chunk_size, chunk_overlap, separators[1:]
            )
            chunks.extend(sub_chunks)

    return chunks
```

**为什么叫"递归"？** 因为超长的 chunk 会被下一级分隔符继续切，层层递进。

### 3.3 策略三：语义分割

按完整句子切分，适合对质量要求高的场景。

```python
import re


def split_sentences(text: str, max_chunk_size: int = 1000) -> list[dict]:
    """
    按句子边界分割（中英文混合）。

    遇到句号、问号、感叹号时切开，但不超过 max_chunk_size。
    """
    # 匹配句子结束位置（中英文标点）
    sentences = re.split(r"(?<=[。！？.!?\n])\s*", text)

    chunks = []
    current = ""

    for sent in sentences:
        if len(current) + len(sent) <= max_chunk_size:
            current += sent
        else:
            if current.strip():
                chunks.append({"text": current})
            current = sent

    if current.strip():
        chunks.append({"text": current})

    return chunks
```

### 3.4 策略四：滑动窗口（Sliding Window with Overlap）

关键思想：相邻 chunk 共享一部分内容，防止关键信息正好落在边界上。

```
chunk_size=800, overlap=100

原文: [字符 0 ───────────────────────────────────── 字符 5000]
                     
chunk_1: [0 ─────────── 800]
chunk_2:       [700 ─────────── 1500]   ← 100 字符重叠
chunk_3:             [1400 ─────────── 2200]
...

重叠的好处:
  "RAG 的核心是检索增强生成。"  ← 这句话在 chunk_1 末尾和 chunk_2 开头都出现
  即使用户的 query 匹配到 chunk_2，
  上下文也不会丢失。
```

```python
def split_with_overlap(
    text: str, chunk_size: int = 800, overlap: int = 100
) -> list[dict]:
    """滑动窗口分割 — 相邻 chunk 共享 overlap 个字符"""
    chunks = []
    start = 0

    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunk_text = text[start:end]

        if chunk_text.strip():
            chunks.append({
                "text": chunk_text,
                "start": start,
                "end": end,
            })

        # 下一个窗口的起始位置
        start += (chunk_size - overlap)

    return chunks
```

---

## 四、chunk_size 和 chunk_overlap 怎么选？

### 4.1 chunk_size 的决策表

| 文档类型 | 推荐 chunk_size | 原因 |
|---------|----------------|------|
| 技术文档 / Wiki | 500-800 | 信息密度高，小块更精准 |
| 法律合同 | 300-500 | 条款粒度细，需要精确匹配 |
| 小说 / 文章 | 800-1200 | 信息密度低，需要更多上下文 |
| 代码 | 200-500 / 按函数切 | 一个函数一个 chunk |
| 对话记录 | 500-800 | 一轮对话一个 chunk |
| FAQ | 200-400 | 一问一答一个 chunk |

### 4.2 chunk_overlap 的决策表

| 信息密度 | 推荐 overlap | 原因 |
|---------|-------------|------|
| 高（代码、法律） | 20-25% of chunk_size | 关键信息可能落在任何位置 |
| 中（技术文档） | 10-15% | 常规保护 |
| 低（小说、新闻） | 5-10% | 语义跨 chunk 的情况少 |

### 4.3 实战调参法

```python
def evaluate_split(
    text: str,
    chunk_size: int,
    chunk_overlap: int,
    test_queries: list[str],
) -> dict:
    """
    评估一组参数的效果。

    打印每个 query 命中了几个 chunk，
    以及命中的 chunk 里是否包含完整答案。
    """
    chunks = split_recursive(text, chunk_size, chunk_overlap)

    print(f"\n=== chunk_size={chunk_size}, overlap={chunk_overlap} ===")
    print(f"共 {len(chunks)} 个 chunk")
    print(f"平均 chunk 长度: {sum(len(c['text']) for c in chunks) / len(chunks):.0f} 字符")
    print(f"最大 chunk: {max(len(c['text']) for c in chunks)} 字符")
    print(f"最小 chunk: {min(len(c['text']) for c in chunks)} 字符")

    for query in test_queries:
        # 简单的关键词命中测试
        hits = sum(1 for c in chunks if query in c["text"])
        print(f"  Query '{query}': {hits} 个 chunk 命中")

    return {"chunks": len(chunks), "avg_size": sum(len(c['text']) for c in chunks) / len(chunks)}


if __name__ == "__main__":
    sample_text = "这是一段很长的测试文本。" * 500

    for size in [400, 800, 1200]:
        for overlap in [0, 100, 200]:
            evaluate_split(sample_text, size, overlap, ["测试文本", "长文本"])
```

**调参口诀：**
```
chunk 太小 → 语义破碎，检索到也看不懂
chunk 太大 → 检索不精准，噪声多
overlap 太小 → 边界信息丢失
overlap 太大 → 冗余多，浪费 token

先定 chunk_size（看文档类型），
再定 overlap = chunk_size × 12%，
最后跑几个 query 验证。
```

---

## 五、完整的分割器类

把上面所有策略整合成一个可用的类：

```python
"""loader_splitter.py — 完整版"""

import fitz
from pathlib import Path
from typing import Literal


class DocumentSplitter:
    """统一的文档加载 + 分割器"""

    def __init__(
        self,
        chunk_size: int = 800,
        chunk_overlap: int = 100,
        strategy: Literal["recursive", "char", "sentence"] = "recursive",
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.strategy = strategy
        self._separators = ["\n\n", "\n", "。", "；", "，", ". ", " ", ""]

    # ─── 加载 ───

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
        pages = []
        doc = fitz.open(file_path)
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
        with open(file_path, "r", encoding="utf-8") as f:
            text = f.read()
        return {"text": text, "metadata": {"source": Path(file_path).name}}

    # ─── 分割 ───

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

    def _split_recursive(self, text: str) -> list[dict]:
        """递归字符分割"""
        if len(text) <= self.chunk_size:
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
```

---

## 六、动手实验

### 🟢 青铜级：加载一份 PDF 并查看结果

```bash
# 找个测试 PDF（或自己打印一个网页为 PDF）
python -c "
from loader_splitter import DocumentSplitter
splitter = DocumentSplitter(chunk_size=500, chunk_overlap=50)
chunks = splitter.split('test_docs/sample.pdf')
print(f'共 {len(chunks)} 个 chunk')
for i, c in enumerate(chunks[:5]):
    print(f'--- Chunk {i+1} ---')
    print(f'  来源: {c[\"metadata\"][\"source\"]} 第{c[\"metadata\"][\"page\"]}页')
    print(f'  长度: {len(c[\"text\"])} 字符')
    print(f'  预览: {c[\"text\"][:100]}...')
"
```

### 🟡 白银级：对比四种分割策略

用同一篇文章，分别用四种策略切，对比 chunk 数量和边界质量。

### 🔴 王者级：写一个分割评估脚本

准备 5 个测试问题，看不同 chunk_size 下每个 query 能命中几个 chunk，找出最优参数。

---

## 七、踩坑记录 🕳️

### 坑 1：PDF 提取的文本是乱码

```
# 某些 PDF 的字体编码特殊，PyMuPDF 可能提取出乱码
# 解决：尝试其他库
pip install pdfplumber  # 备选方案
pip install pymupdf4llm  # 专门为 LLM 场景优化
```

### 坑 2：PDF 的表格变成了一行一个单元格

PyMuPDF 把表格提取为逐行文本，表格结构丢失。解决方案：用 `pymupdf4llm` 或 LangChain 的 `UnstructuredPDFLoader`。

### 坑 3：chunk_overlap 太大导致重复

```python
# chunk_size=500, overlap=400
# → 每个 chunk 只有 100 个新字符
# → 10K 的文章切出 100 个 chunk，大量重复
# → 检索结果高度冗余
```

**overlap 建议不超过 chunk_size 的 25%。**

### 坑 4：空 chunk

某些页可能是空白页、纯图片页、或只有页眉页脚。分割结果中可能出现 `{"text": ""}` 或 `{"text": "  "}`。**每个 split 方法里都要过滤空 chunk。**

### 坑 5：元数据丢失

```python
# ❌ 分割后 metadata 没了
chunk = {"text": "..."}  # 丢失了来源页码

# ✅ 保留 metadata
chunk = {
    "text": "...",
    "metadata": {"source": "doc.pdf", "page": 3}
}
```

检索到 chunk 后，需要告诉用户这个信息来自哪里。**来源引用靠 metadata。**

---

## 八、副线笔记

### Claude Code 怎么"分割"大文件？

当你让 Claude Code 处理一个 3000 行的大文件时，它不会一次读完——它会：
1. 先读关键部分（import、类定义、函数签名）
2. 需要细节时再用 `Read` 工具精确定位
3. 上下文满时自动 compact（压缩早期对话）

这和 RAG 的 "粗检索 + 精排"是一样的策略。**Claude Code 的 compact 就是它的"chunking"。**

### 今天的观察任务

- 打开一个 500 行以上的文件，看 Claude Code 一次读多少行
- 它的"分割边界"在哪——函数边界？类边界？还是你标记的位置？
- 比较一下：它的分割策略和你的递归字符分割有什么不同？

---

## 今日产出检查清单

- [ ] 能加载 PDF 并逐页提取文本
- [ ] 实现了递归字符分割器
- [ ] 理解 chunk_size 和 overlap 对检索的影响
- [ ] 能说出四种分割策略的适用场景
- [ ] 对比过不同 chunk_size 下的 chunk 数量和预览质量

---

> **下一课预告：Day 03 — 向量数据库 + 检索**。把分好的 chunk Embed 化，存进 Chroma，实现你的第一次语义检索。
