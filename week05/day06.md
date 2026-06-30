# Day 06 — 量化压缩 + Claude Code Hooks 自动化

## 学习目标

主线讲量化压缩：当向量库规模从几千涨到百万级，内存会先于 CPU 成为瓶颈。今天拆开三种主流量化方式（SQ / PQ / Binary），讲清楚压缩比与召回的权衡，并手写一遍 SQ 量化。副线讲 Claude Code Hooks——这是 Week 04 Day 07 预告过的"Week 05 会教你写 Hook"，今天兑现：让 Claude Code 在工具执行前后自动触发脚本，把知识库的校验、备份工作流自动化。

学完今天你能：
1. 算清楚向量库的内存账：100 万条 1024 维为什么是 4GB
2. 区分 SQ / PQ / Binary 三种量化的压缩比、召回损失、适用场景
3. 实现量化向量粗排 + 原向量精排的两阶段检索
4. 写一个 PostToolUse Hook，自动校验入库文档的 frontmatter

---

## 一、为什么需要量化：向量内存会爆炸

向量库的内存账，先算明白。

```
单条向量内存 = 维度 × 每维字节数

Embedding 模型常见维度：
  nomic-embed-text  → 768 维
  bge-large-zh      → 1024 维
  OpenAI text-embedding-3-large → 3072 维

每维默认 float32 = 4 字节

100 万条 × 1024 维 × 4 字节 = 4,096,000,000 字节 ≈ 4 GB
```

4GB 看着还行？这只是"裸向量"。真实部署里你还要存：

| 存储项 | 占用（100万条估算） |
|--------|---------------------|
| 原始向量（float32） | 4 GB |
| HNSW 索引图（M=16，每节点约 32 条边） | ~2 GB |
| 元数据（source / page / tags） | ~0.5 GB |
| 文本原文 chunk | ~1 GB |
| 合计 | ~7.5 GB |

7.5GB 全放内存，单机扛 100 万条已经吃力。如果上到 1000 万条，单机 75GB 内存根本买不起。**量化的本质：用一点点精度，换大幅度的内存下降。**

```
量化前：float32（每维 4 字节）→ 4 GB
SQ 量化后：int8（每维 1 字节）→ 1 GB      ← 4 倍压缩
PQ 量化后：每条向量 64 字节        → 64 MB   ← 64 倍压缩
二值量化后：每维 1 bit            → 128 MB  ← 32 倍压缩
```

---

## 二、三种量化方式

### 2.1 SQ（标量量化 Scalar Quantization）

**一句话：把 float32 的连续值，压成 int8 的 256 个离散桶。**

```python
# 伪代码：SQ 量化的核心
# float32 范围 [-1.0, 1.0] → 映射到 int8 [0, 255]
scale = 255 / (max_val - min_val)
quantized = (vector - min_val) * scale          # 量化：float → int8
restored = quantized / scale + min_val          # 反量化：int8 → float（有误差）
```

- 压缩比：4 倍（float32 → int8）
- 召回损失：很小（通常 < 2%）
- 查询速度：略快（int8 运算更快）
- 适用场景：**生产首选**，召回敏感、又想省内存

### 2.2 PQ（乘积量化 Product Quantization）

**一句话：把一条长向量切成 N 段，每段单独聚类成一个码本，向量变成"一组码本索引"。**

```
1024 维向量 → 切成 16 段，每段 64 维
  每段用 k-means 聚成 256 类（1 字节编码）
  → 整条向量 = 16 字节（原本 4096 字节）

粗量化 + 细量化：
  粗量化：先用 IVF 把空间分成 N 个 cell，查询时只搜最近的几个 cell
  细量化：在每个 cell 内部用 PQ 编码向量
  → IVF_PQ = 粗筛 + 细编码，万级到亿级数据的标配
```

- 压缩比：10-50 倍（取决于切段数和码本大小）
- 召回损失：中等（5-15%，可通过 re-rank 补回）
- 查询速度：极快（只比较码本索引）
- 适用场景：**超大规模**（亿级）、内存极度受限

### 2.3 二值量化（Binary Quantization）

**一句话：向量每个分量只保留符号位，正数变 1，负数变 0。**

```python
# 二值量化
binary_vec = (vector > 0).astype(np.uint8)   # float → 0/1
# 距离用汉明距离（XOR 后数 1 的个数），CPU 位运算极快
```

- 压缩比：32 倍（float32 → 1 bit）
- 召回损失：较大（10-25%，必须配合 re-rank）
- 查询速度：极快（汉明距离用位运算）
- 适用场景：**初筛粗排**，先二值向量快速召回 top 100，再用原向量精排

### 2.4 三种量化对比

| 方式 | 压缩比 | 召回损失 | 查询速度 | 适用场景 |
|------|--------|----------|----------|----------|
| SQ（int8） | 4 倍 | < 2%（极小） | 略快 | 生产首选，召回敏感 |
| PQ（码本） | 10-50 倍 | 5-15%（中） | 极快 | 亿级数据，内存吃紧 |
| Binary（1 bit） | 32 倍 | 10-25%（大） | 极快 | 粗排初筛，配合 re-rank |
| 不量化（float32） | 1 倍 | 0% | 基准 | 数据量小（< 10万），追求零损失 |

**选型口诀：** 小数据不量化；百万级用 SQ；亿级用 PQ；要极致速度先 Binary 粗排再精排。

---

## 三、量化与召回的权衡：两阶段检索

量化必然丢精度。工业界标准解法：**粗排用量化向量（快），精排用原向量（准）。**

```
查询流程（两阶段）：
  1. query 向量量化（用同样的量化方式）
  2. 在量化向量库上算距离 → 召回 top 100（快，但可能不准）
  3. 取这 100 条的原向量 → 重新算精确距离 → 重排取 top 10（准）
```

```python
"""two_stage_retrieval.py — 量化粗排 + 原向量精排"""

import numpy as np


def two_stage_search(
    query: np.ndarray,
    quantized_db: np.ndarray,   # 量化后的向量库（uint8）
    original_db: np.ndarray,    # 原始向量库（float32）
    min_val: np.ndarray,
    scale: np.ndarray,
    top_k: int = 10,
    coarse_n: int = 100,
) -> list[int]:
    """两阶段检索：量化粗排 + 原向量精排

    参数:
        query:        查询向量（float32，未量化）
        quantized_db: 量化后的向量库（uint8）
        original_db:  原始向量库（float32）
        min_val:      量化时记录的每维最小值
        scale:        量化时记录的每维缩放系数
        top_k:        最终返回数量
        coarse_n:     粗排召回数量
    返回:
        精排后的 top_k 索引列表
    """
    # 阶段 1：量化 query，在量化库上粗排
    safe_scale = np.where(scale > 0, scale, 1.0)
    q_quantized = np.clip((query - min_val) * safe_scale, 0, 255).astype(np.uint8)
    # uint8 上算 L2 距离（极快）
    coarse_dist = np.linalg.norm(
        quantized_db.astype(np.float32) - q_quantized, axis=1
    )
    coarse_top = np.argpartition(coarse_dist, coarse_n)[:coarse_n]

    # 阶段 2：取粗排结果的原向量，精排
    fine_dist = np.linalg.norm(original_db[coarse_top] - query, axis=1)
    fine_order = np.argsort(fine_dist)[:top_k]

    return coarse_top[fine_order].tolist()
```

**为什么这么设计？** 量化向量粗排只比较 uint8，100 万条 0.1 秒搞定；精排只在 100 条原向量上算，耗时忽略不计。既快又准。

---

## 四、各向量库的量化支持

| 库 | SQ | PQ | Binary | 配置方式 |
|------|-----|-----|--------|----------|
| Qdrant | 内置 | 内置 | 内置 | 建集合时设 `quantization_config` |
| Milvus | IVF_SQ8 | IVF_PQ | 不支持 | 建索引时指定索引类型 |
| Chroma | 不直接支持 | 不支持 | 不支持 | 需手动量化后存（库本身存 float32） |
| Pinecone | 自动 | 自动 | 自动 | 服务端自动管理，无需配置 |

### Qdrant 配置示例（内置量化最完整）

```python
from qdrant_client import QdrantClient
from qdrant_client.models import (
    VectorParams, ScalarQuantization, ScalarQuantizationConfig,
    ScalarType,
)

client = QdrantClient(host="localhost", port=6333)

# 建集合时同时开启 SQ 量化
client.create_collection(
    collection_name="routes",
    vectors_config=VectorParams(size=1024, distance="Cosine"),
    quantization_config=ScalarQuantization(
        scalar=ScalarQuantizationConfig(
            type=ScalarType.INT8,        # float32 → int8
            quantile=0.99,               # 截掉 1% 极值，抗噪
            always_ram=True,             # 量化向量常驻内存，原向量按需加载
        ),
    ),
)
```

### Milvus 配置示例（IVF_SQ8 索引）

```python
# 索引类型直接选 IVF_SQ8：IVF 粗筛 + SQ8 量化
index_params = {
    "index_type": "IVF_SQ8",      # IVF + Scalar Quantization 8-bit
    "metric_type": "COSINE",
    "params": {"nlist": 1024},    # IVF 聚类中心数
}
collection.create_index(field_name="embedding", index_params=index_params)
```

### Chroma 的现状

Chroma 暂不内置量化，内部统一存 float32。可以手动量化后把 uint8 数组当 metadata 存、查询时自己算距离——但**生产别这么干**：量小直接用 float32，量大换 Qdrant / Milvus。这也是 Day 05 选型决策树里的一个分叉点。

---

## 五、手写 SQ 量化演示：quantization_demo.py

下面用 numpy 从零实现 SQ 量化，测出真实的压缩比和召回误差。这是今天的核心产出文件，存到 `week05/quantization_demo.py`。

```python
"""quantization_demo.py — 标量量化（SQ）从零实现与效果演示

演示内容：
1. 生成模拟向量库（10000 条 × 1024 维，float32）
2. SQ 量化：float32 → uint8，记录 min/scale
3. 反量化：uint8 → float32，计算误差
4. 对比量化前后的内存占用和检索召回率
"""

import numpy as np


def sq_quantize(vectors: np.ndarray):
    """SQ 标量量化：float32 → uint8

    参数:
        vectors: float32 向量库，shape (N, D)
    返回:
        quantized: 量化后的 uint8 向量库
        min_val:   每维最小值（反量化用）
        scale:     每维缩放系数（反量化用）
    """
    min_val = vectors.min(axis=0)                      # 每维最小值
    max_val = vectors.max(axis=0)                      # 每维最大值
    scale = np.where(
        (max_val - min_val) > 0,
        255.0 / (max_val - min_val),
        0.0,                                            # 防止除零（padding 维）
    )
    quantized = np.clip(
        (vectors - min_val) * scale, 0, 255
    ).astype(np.uint8)                                 # float → uint8
    return quantized, min_val, scale


def sq_dequantize(quantized: np.ndarray, min_val: np.ndarray, scale: np.ndarray):
    """SQ 反量化：uint8 → float32（有损还原）"""
    safe_scale = np.where(scale > 0, scale, 1.0)
    return quantized.astype(np.float32) / safe_scale + min_val


def recall_at_k(original_result: list, quantized_result: list, k: int = 10) -> float:
    """计算 top-k 召回率：量化结果中命中原结果的比例"""
    orig_set = set(original_result[:k])
    quant_set = set(quantized_result[:k])
    return len(orig_set & quant_set) / k


def main():
    # 1. 生成模拟向量库（已归一化，模拟真实 embedding）
    np.random.seed(42)
    N, D = 10000, 1024
    print(f"生成模拟向量库：{N} 条 × {D} 维")
    vectors = np.random.randn(N, D).astype(np.float32)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)   # L2 归一化

    # 2. 量化
    quantized, min_val, scale = sq_quantize(vectors)
    restored = sq_dequantize(quantized, min_val, scale)

    # 3. 内存对比
    print("\n=== 内存占用 ===")
    print(f"原始（float32）: {vectors.nbytes / 1024:.1f} KB")
    print(f"量化后（uint8） : {quantized.nbytes / 1024:.1f} KB")
    print(f"压缩比         : {vectors.nbytes / quantized.nbytes:.1f}x")

    # 4. 误差分析
    mae = np.mean(np.abs(vectors - restored))
    print(f"\n=== 量化误差 ===")
    print(f"平均绝对误差 MAE: {mae:.6f}")

    # 5. 检索召回对比
    query = vectors[0]                                            # 用第 0 条当查询
    orig_dist = np.linalg.norm(vectors - query, axis=1)
    quant_dist = np.linalg.norm(restored - query, axis=1)

    orig_top = np.argsort(orig_dist)[1:101].tolist()            # 排除自己
    quant_top = np.argsort(quant_dist)[1:101].tolist()

    print(f"\n=== 检索召回 ===")
    for k in [1, 5, 10, 50, 100]:
        r = recall_at_k(orig_top, quant_top, k)
        print(f"Recall@{k:<3}: {r:.2%}")


if __name__ == "__main__":
    main()
```

预期输出（参考）：

```
=== 内存占用 ===
原始（float32）: 40000.0 KB
量化后（uint8） : 10000.0 KB
压缩比         : 4.0x

=== 量化误差 ===
平均绝对误差 MAE: 0.0009xx

=== 检索召回 ===
Recall@1  : 100.00%
Recall@5  : 100.00%
Recall@10 : 90.00%
Recall@50 : 94.00%
Recall@100: 96.00%
```

**结论：** SQ 量化 4 倍压缩，召回损失通常在 5% 以内——这就是生产首选的原因。

---

## 六、副线：Claude Code Hooks 机制详解

### 6.1 Hook 是什么

Hook 是 Claude Code 在**执行工具前后自动触发的脚本**。和 Slash Command 最大的区别：

```
Slash Command：你主动输入 /rag-index → Claude Code 执行
Hook          ：Claude Code 要写文件 → 自动触发你的校验脚本 → 你不用记得调用
```

### 6.2 两类 Hook

| Hook 类型 | 触发时机 | 能做什么 | 典型场景 |
|-----------|----------|----------|----------|
| PreToolUse | 工具执行**前** | 拦截、校验、修改参数 | 禁止写敏感文件、校验路径 |
| PostToolUse | 工具执行**后** | 校验结果、备份、追加操作 | 校验入库数据、自动备份 |

### 6.3 配置结构

Hook 配置放在 `.claude/settings.json` 的 `hooks` 字段（也可单独建 hooks 文件再引用）：

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          {
            "type": "command",
            "command": "python .claude/hooks/validate_frontmatter.py"
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "python .claude/hooks/block_dangerous_cmd.py"
          }
        ]
      }
    ]
  }
}
```

字段说明：
- `matcher`：匹配工具名（`Write`、`Edit`、`Bash` 等），`|` 表示多选
- `type`：目前固定 `command`
- `command`：要执行的 shell 命令，Hook 脚本通过 stdin 拿到 JSON 上下文（含工具名、参数、文件路径等）

---

## 七、实战 Hook：PostToolUse 自动校验知识库文档

### 7.1 场景

知识库里每个 `.md` 文档必须有 frontmatter（`title` / `source` / `tags`），否则后续索引时元数据缺失、过滤失效。让 Claude Code 每次写完 `.md` 自动校验，缺字段就提示自己补全。

### 7.2 Hook 配置

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          {
            "type": "command",
            "command": "python .claude/hooks/validate_frontmatter.py"
          }
        ]
      }
    ]
  }
}
```

### 7.3 校验脚本

```python
"""validate_frontmatter.py — PostToolUse Hook 脚本

当 Claude Code 执行完 Write/Edit 后触发，
校验刚写入的 .md 文件是否含必要 frontmatter（title / source / tags）。
缺字段则输出警告到 stderr，非零退出码触发 Claude Code 关注并自行修正。
"""

import sys
import os
import json
import re


REQUIRED_FIELDS = ["title", "source", "tags"]


def extract_frontmatter(content: str) -> dict:
    """从 Markdown 内容提取 YAML frontmatter"""
    match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return {}
    fields = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            fields[key.strip()] = val.strip()
    return fields


def main():
    # Claude Code 通过 stdin 传 JSON 上下文
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)                              # 解析失败直接放行，不阻塞工作流

    file_path = payload.get("tool_input", {}).get("file_path", "")

    # 非 md 文件，跳过
    if not file_path.endswith(".md"):
        sys.exit(0)

    if not os.path.exists(file_path):
        print(f"[Hook] 文件不存在: {file_path}", file=sys.stderr)
        sys.exit(0)

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    front = extract_frontmatter(content)
    missing = [k for k in REQUIRED_FIELDS if k not in front]

    if missing:
        # 输出到 stderr，Claude Code 会读到并提示自己补全
        print(
            f"[Hook 警告] {file_path} 缺少 frontmatter 字段: {missing}\n"
            f"请补充必要元数据后再入库，否则向量库元数据过滤会失效。",
            file=sys.stderr,
        )
        sys.exit(2)                             # 非零退出码触发 Claude Code 关注
    else:
        print(f"[Hook] frontmatter 校验通过: {file_path}")


if __name__ == "__main__":
    main()
```

### 7.4 目录结构

```
.claude/
├── settings.json                 # hooks 配置在这里
├── commands/                     # Day 04-05 的 Slash Command 还在这
│   ├── rag-index.md
│   └── rag-ask.md
└── hooks/
    └── validate_frontmatter.py   # 今天新增的 Hook 脚本
```

---

## 八、动手实验

### 🟢 青铜级：跑通 SQ 量化

把上面的 `quantization_demo.py` 存到 `week05/` 下跑一遍，记录压缩比和 Recall@10，体会"4 倍压缩换 < 5% 召回损失"这笔账。

### 🟡 白银级：写一个 PostToolUse Hook

按 7.2 / 7.3 配置 `.claude/hooks/validate_frontmatter.py`，让 Claude Code 写一个缺 frontmatter 的 md 文件，观察 Hook 是否触发警告、Claude Code 是否自动补字段。

### 🔴 王者级：两阶段检索 + Binary 量化

在 `quantization_demo.py` 基础上加 Binary 量化粗排（top 100）+ 原向量精排（top 10），对比纯 float32 检索的召回率与耗时，写进踩坑记录。

---

## 九、踩坑记录 🕳️

**坑 1：PQ 量化召回突然暴跌到 40%**
原因：切段数设太少（如 1024 维只切 4 段，每段 256 维），码本表达力不足。
解决：切段数 ≈ 维度 / 64 是经验值，1024 维切 16 段比较稳；码本大小 256 是甜点。

**坑 2：SQ 量化后某些维度 max == min，scale 除零报错**
原因：某些维度全是相同值（如 padding 维、稀疏特征）。
解决：`np.where(max - min > 0, scale, 0)`，反量化时 scale 为 0 的维度直接还原成 min_val，避免 NaN 污染整条向量。

**坑 3：Qdrant 开了量化，召回反而比不开还低**
原因：`always_ram=False` 时量化向量走磁盘，反而拖慢且不一致；或 `quantile` 设太小（如 0.9）丢了太多信息。
解决：召回敏感场景 `always_ram=True`、`quantile=0.99`；先在小数据集测 recall 再上生产。

**坑 4：Hook 配置不生效**
原因：`matcher` 写错工具名（如写成小写 `write`），或 JSON 放错层级（放成顶层而非 `hooks.PostToolUse` 下）。
解决：工具名首字母大写（`Write`/`Edit`/`Bash`），用 Claude Code 设置面板验证配置是否被识别，改完重启会话。

**坑 5：Hook 脚本里读不到文件路径**
原因：Hook 脚本通过 stdin 拿 JSON，不是命令行参数；版本间字段名可能有差异。
解决：先 `print(payload)` 把 stdin 内容打到日志确认字段名，再写解析逻辑；解析失败要 `sys.exit(0)` 放行，别让 Hook 阻塞主流程。

---

## 十、副线笔记：Hooks 实战心得

### Hook 和 Slash Command 的区别

| 维度 | Slash Command | Hook |
|------|---------------|------|
| 触发方式 | 你主动输入 `/xxx` | 事件自动触发（工具执行前后） |
| 你需要记得吗 | 需要，忘了就不会跑 | 不需要，永远在背景运行 |
| 适合什么 | 一次性的复杂工作流 | 每次都该做的校验/兜底 |
| 失败影响 | 你看到错误自己处理 | 非零退出码提示 Claude Code 修正 |

**一句话：** Command 是"我主动要做的流程"，Hook 是"无论谁做都该过的关卡"。

### 适合用 Hook 自动化的知识库管理场景

1. **入库前元数据校验**：写完 `.md` 自动检查 frontmatter（title/source/tags），缺字段就拦下——今天就是这个。
2. **索引后自动备份**：PostToolUse 监听向量库写入，每次更新后 `cp -r chroma_db chroma_db.bak`，防止手滑误删。
3. **危险命令拦截**：PreToolUse 监听 Bash，匹配到 `rm -rf chroma_db` 或 `DROP TABLE` 就阻断，给一次反悔机会。

### 什么时候别用 Hook

- 逻辑复杂、需要多轮对话的 → 用 Slash Command
- 只在你个人开发时偶尔跑的 → 直接手敲命令
- Hook 脚本本身依赖 LLM 调用的 → 别在 Hook 里调 LLM，会拖慢每次工具调用

---

## 今日产出检查清单

- [ ] 跑通 `quantization_demo.py`，记录 SQ 压缩比和 Recall@10
- [ ] 理解 SQ / PQ / Binary 三种量化的压缩比与召回损失差异
- [ ] 实现量化粗排 + 原向量精排的两阶段检索
- [ ] 在 `.claude/settings.json` 配置了 PostToolUse Hook
- [ ] `validate_frontmatter.py` 能正确校验 frontmatter 并触发警告
- [ ] 能说清 Hook 和 Slash Command 的区别与各自适用场景

---

> **下一课预告：Day 07 — 综合实战：徒步路线知识库语义搜索**。把本周的 ANN / HNSW / 量化压缩全部用上，搭一个 FastAPI + 向量库 + 多维过滤的路线语义搜索系统，全程 Claude Code 结对编程。
