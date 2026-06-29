# RAG（检索增强生成）技术详解

## 1. 什么是 RAG

RAG（Retrieval-Augmented Generation，检索增强生成）是一种将**信息检索**与**文本生成**相结合的 AI 技术。它由 Meta AI 在 2020 年提出，旨在解决大语言模型（LLM）的以下问题：

- **知识时效性**：LLM 的训练数据有截止日期，无法获取最新信息
- **幻觉问题**：LLM 可能生成看似合理但实际错误的内容
- **领域知识缺失**：通用 LLM 对专业领域知识的掌握有限
- **数据隐私**：企业数据不应直接输入公开的 LLM

### RAG 的核心思想

RAG 的基本流程是：
1. **索引阶段**：将外部知识文档切分成小片段（Chunk），通过 Embedding 模型转化为向量，存储到向量数据库中
2. **检索阶段**：用户提问时，将问题转为向量，在向量数据库中检索最相关的文档片段
3. **生成阶段**：将检索到的相关片段作为上下文，拼接到 Prompt 中，让 LLM 基于这些上下文生成回答

这种方式让 LLM 能够基于"真实参考资料"来回答问题，大大减少了幻觉并提高了回答的准确性。

## 2. Embedding（向量化）

Embedding 是将文本转化为高维向量（通常 256-4096 维）的过程。

### 2.1 常见 Embedding 模型

| 模型 | 维度 | 特点 |
|------|------|------|
| OpenAI text-embedding-3-small | 1536 | 性能好，需联网 |
| OpenAI text-embedding-3-large | 3072 | 更高精度 |
| nomic-embed-text | 768 | 开源，可本地运行 |
| bge-large-zh | 1024 | 中文优化 |
| m3e-base | 768 | 中文多场景 |

### 2.2 文本相似度计算

向量之间的相似度通常用**余弦相似度**计算：

```
cosine_similarity(A, B) = (A · B) / (||A|| × ||B||)
```

取值范围为 [-1, 1]，值越接近 1 表示越相似。向量数据库通常使用余弦距离（1 - 相似度），越小表示越相似。

### 2.3 本地 Embedding 服务

可以使用 Ollama 在本地运行 Embedding 模型：

```bash
# 拉取模型
ollama pull nomic-embed-text

# 启动服务（默认端口 11434）
ollama serve
```

调用接口：
```
POST http://localhost:11434/api/embeddings
Body: {"model": "nomic-embed-text", "prompt": "要向量化的文本"}
```

## 3. 向量数据库

向量数据库（Vector Database）是专门用于存储和检索向量的数据库。

### 3.1 主流向量数据库

| 数据库 | 类型 | 特点 |
|--------|------|------|
| Chroma | 嵌入式/服务端 | 轻量，适合原型开发，Python 友好 |
| Milvus | 分布式 | 高性能，支持大规模数据 |
| Pinecone | 云服务 | 全托管，开箱即用 |
| Weaviate | 开源/云 | 语义搜索，支持混合检索 |
| FAISS | 库（非数据库） | Meta 开源，极致性能 |
| Qdrant | 分布式 | Rust 编写，高性能 |

### 3.2 ChromaDB 使用示例

Chroma 是最易上手的向量数据库，适合学习和原型开发。

```python
import chromadb
from chromadb.config import Settings

# 创建持久化客户端
client = chromadb.PersistentClient(
    path="./chroma_db",
    settings=Settings(anonymized_telemetry=False)
)

# 创建集合
collection = client.get_or_create_collection(
    name="documents",
    metadata={"hnsw:space": "cosine"}
)

# 添加文档
collection.add(
    ids=["doc1_chunk0", "doc1_chunk1"],
    documents=["这是第一段文本", "这是第二段文本"],
    metadatas=[{"source": "doc1.pdf", "page": "1"}, {"source": "doc1.pdf", "page": "2"}],
    embeddings=[[0.1, 0.2, ...], [0.3, 0.4, ...]]
)

# 查询最相似的文档
results = collection.query(
    query_embeddings=[[0.15, 0.25, ...]],
    n_results=5,
    include=["documents", "metadatas", "distances"]
)
```

### 3.3 向量索引算法

Chroma 使用 HNSW（Hierarchical Navigable Small World）算法进行近似最近邻搜索。HNSW 是一种基于图的高效索引结构，能在毫秒级别完成百万级向量的检索。

## 4. 文档分割策略

将长文档切分为适当大小的片段（Chunk）是 RAG 系统中的关键步骤。

### 4.1 分割策略对比

| 策略 | 原理 | 优点 | 缺点 |
|------|------|------|------|
| 递归字符分割 | 按分隔符层级递归切分 | 保持语义完整性 | 可能产生不均匀的片段 |
| 固定长度分割 | 按固定字符数切分 | 简单可控 | 可能切断句子 |
| 句子分割 | 按句号等标点切分 | 保持句子完整 | 片段长度不均匀 |
| 语义分割 | 用模型判断语义边界 | 最佳语义保持 | 计算开销大 |

### 4.2 分割参数调优

- **chunk_size（片段大小）**：通常 500-1000 字符。太大则检索不精确，太小则缺乏上下文
- **chunk_overlap（重叠大小）**：通常为 chunk_size 的 10%-20%，避免信息在边界处丢失

推荐配置：
```python
splitter = DocumentSplitter(
    chunk_size=800,
    chunk_overlap=100,
    strategy="recursive"
)
```

## 5. Query Rewriting（查询改写）

在多轮对话场景中，用户经常会使用指代词（如"它"、"上面的"）或省略上下文，导致独立的问题缺乏完整语义。

Query Rewriting 的作用是将用户当前问题结合对话历史，改写为一个独立的、语义完整的问题。

### 示例

对话历史：
- 用户："Python 的 GIL 是什么？"
- 助手："GIL（全局解释器锁）是..."

当前问题："它有什么影响？"

改写后："Python 的 GIL 有什么影响？"

### 实现方式

通常通过 LLM 来完成 Query Rewriting：
1. 构造包含对话历史的 Prompt
2. 让 LLM 将当前问题改写为独立完整的问题
3. 如果 LLM 调用失败，安全降级为原始问题

## 6. Prompt 工程

RAG 系统中的 Prompt 设计对最终回答质量影响很大。

### 标准 RAG Prompt 结构

```
你是一个智能问答助手。请根据以下提供的参考文档内容，回答用户的问题。
如果参考文档中没有相关信息，请明确说明你不知道，不要编造答案。

参考文档：
[1] 第一段相关文本...
[2] 第二段相关文本...
[3] 第三段相关文本...

用户问题：用户提出的问题

请基于参考文档给出准确、简洁的回答：
```

### Prompt 设计要点

1. **角色设定**：明确 AI 的身份和能力边界
2. **约束条件**：要求"不要编造"、"只基于参考文档"
3. **格式规范**：指定回答的结构和长度
4. **来源引用**：要求标注信息来源，增强可信度

## 7. SSE 流式输出

SSE（Server-Sent Events）是一种服务器向客户端推送数据的协议。

### SSE 协议格式

```
event: message
data: {"delta": "你", "done": false}

event: message
data: {"delta": "好", "done": false}

event: message
data: {"delta": "", "done": true, "sources": [...]}
```

### 优点

- 基于标准 HTTP 协议，无需 WebSocket
- 服务端单向推送，适合 LLM 流式输出场景
- 自动重连机制，网络中断时可恢复
- 浏览器原生支持（EventSource API）

## 8. RAG 系统评估指标

评估 RAG 系统的效果通常从以下维度衡量：

### 8.1 检索质量

- **召回率（Recall）**：相关文档被检索到的比例
- **精确率（Precision）**：检索到的文档中相关的比例
- **MRR（Mean Reciprocal Rank）**：第一个相关结果的排名倒数的平均值

### 8.2 生成质量

- **忠实度（Faithfulness）**：回答是否忠于检索到的上下文
- **相关性（Relevance）**：回答是否与用户问题相关
- **完整性（Completeness）**：回答是否充分覆盖了问题

### 8.3 端到端指标

- **回答准确性**：与标准答案的匹配度
- **响应延迟**：从提问到回答完成的时间
- **用户满意度**：用户对回答质量的主观评价
