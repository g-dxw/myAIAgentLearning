# Day 04 — Shadow Testing + 回归测试 + CI 集成

## 学习目标

Day 03 我们用 RAGAS 量化了 RAG 质量，用 Promptfoo 对比了 prompt 版本。但那都是"本地手动跑一遍评估"——你改完 prompt，手动跑 RAGAS，看分数变了没。这有几个问题：

1. RAGAS 评估的是"测试集上的表现"，但生产环境的真实流量你测不到
2. 你改完 Agent 本地测着没问题，上线后用户反馈才发现退化
3. 每次改 Agent 都要手动跑测试，太累，而且容易忘

今天解决这三个问题。学完今天你能：

1. 理解 Shadow Testing 的原理：新旧 Agent 并行跑同一任务，对比输出差异
2. 掌握回归测试的核心：改了 prompt/工具后，确保已有功能不退化
3. 能用 pytest 写 Agent 回归测试，集成到 CI 流程
4. 理解 GitHub Actions 如何自动运行 Agent 测试

---

## 一、Shadow Testing：升级 Agent 的安全网

### 1.1 场景：改 Agent 的两难

回忆一下你这两周改 Agent 的经历：

- Week 06 改了 system_prompt，从"徒步助手"升级到"CMA 教练人设"
- Week 07 加了多 Agent 协作，新建了 Planner 和 Executor
- Day 03 用 Promptfoo 对比了两个 prompt 版本，发现 v2 更好

每次改完，你心里都有点慌：**改好了 A 功能，会不会搞坏了 B 功能？** 你用 Promptfoo 跑了 10 个测试用例都通过了，但生产环境里用户问的问题千奇百怪，测试集覆盖不到。

这就是"改 Agent 的两难"：

| 方式 | 问题 |
|------|------|
| 直接上线新版本 | 风险大，用户可能立刻碰到退化 |
| 本地多测几轮再上线 | 测试集有限，覆盖不全；而且手动测慢 |
| 灰度发布（10% 流量切新版本） | 一旦退化，10% 用户已经受影响 |

Shadow Testing 是第四种选择：**新旧版本并行跑生产流量，新版本只记录不返回，对比差异后再决定上不上线。**

### 1.2 Shadow Testing 的原理

Shadow Testing（影子测试）的核心思路：

- 新旧 Agent 同时接收相同请求
- 旧 Agent 的结果给用户（安全，保证用户体验）
- 新 Agent 的结果只记录不返回（影子，用户看不到）
- 对比两者差异，差异小才上线新版本

ASCII 图：

```
用户请求 → 旧 Agent → 回复用户（生产）
         → 新 Agent → 记录结果（影子，用户看不到）
                       ↓
                  对比新旧差异
                  差异大 → 不上线
                  差异小 → 切换到新版本
```

注意"只记录不返回"这点——新 Agent 的结果用户完全看不到。这意味着即使新版本有严重 bug，也不会影响线上用户。这比灰度发布更安全：灰度发布的 10% 用户会真拿到新版本结果，而 Shadow Testing 是 0% 用户拿到新版本结果。

> **前端类比：** Shadow Testing 就像前端灰度发布前，先在内部用 Playwright 跑一遍新代码，对比新旧版本的页面截图差异。差异小才敢放给真实用户。区别是前端的"差异"是像素级的，Agent 的"差异"是语义级的。

### 1.3 代码实现

```python
"""shadow_test.py — Shadow Testing 实现

新旧 Agent 并行跑同一任务，对比输出差异。
新 Agent 的结果只记录，不返回给用户。
"""
import asyncio


async def shadow_test(old_agent, new_agent, test_cases):
    """新旧 Agent 并行跑同一任务"""
    results = []
    for tc in test_cases:
        # 旧 Agent 结果（生产）
        old_result = await old_agent.ainvoke(tc.input)
        # 新 Agent 结果（影子）
        new_result = await new_agent.ainvoke(tc.input)

        # 对比差异
        diff = compare_results(old_result, new_result)
        results.append({
            "task": tc.task_id,
            "old": old_result,
            "new": new_result,
            "diff_score": diff.score,
            "diff_type": diff.type,
        })

    # 汇总
    avg_diff = sum(r["diff_score"] for r in results) / len(results)
    print(f"平均差异度: {avg_diff:.2f}")
    if avg_diff > 0.15:
        print("警告：差异过大，不建议上线新版本")
    return results
```

### 1.4 怎么算"差异度"

Shadow Testing 最难的部分是 `compare_results`——怎么算"新旧输出差异多大"。Agent 输出是自然语言，不能简单用字符串相等判断。常见的三种方式：

| 方式 | 做法 | 优点 | 缺点 |
|------|------|------|------|
| 关键词重合度 | 新旧答案的关键词重合比例 | 快、便宜 | 语义相同用词不同会被判为差异大 |
| LLM-as-Judge | 让 LLM 判断两个答案语义是否一致 | 准 | 慢、贵、自己也消耗 token |
| Embedding 相似度 | 新旧答案 embedding 向量的余弦相似度 | 中庸 | 需要 embedding 模型 |

```python
"""compare_results.py — 差异对比实现（embedding 方式）"""
from langchain_openai import OpenAIEmbeddings


class DiffResult:
    def __init__(self, score: float, diff_type: str):
        self.score = score       # 0=完全不同，1=完全一致
        self.diff_type = diff_type


def compare_embedding(old_answer: str, new_answer: str) -> float:
    """embedding 相似度（余弦相似度，越接近1越相似）"""
    embeddings = OpenAIEmbeddings()
    vec_old = embeddings.embed_query(old_answer)
    vec_new = embeddings.embed_query(new_answer)
    dot = sum(a * b for a, b in zip(vec_old, vec_new))
    norm_old = sum(a * a for a in vec_old) ** 0.5
    norm_new = sum(b * b for b in vec_new) ** 0.5
    return dot / (norm_old * norm_new) if norm_old and norm_new else 0.0


def compare_results(old_result, new_result) -> DiffResult:
    """对比新旧 Agent 的输出，返回差异度"""
    old_answer = old_result["messages"][-1].content
    new_answer = new_result["messages"][-1].content
    score = compare_embedding(old_answer, new_answer)
    # diff_score 用 1 - 相似度 表示"差异度"（越大越不同）
    return DiffResult(score=1 - score, diff_type="semantic")
```

差异度阈值 0.15 是个经验值——意思是新旧答案平均有 15% 的语义差异。这个阈值怎么定没有标准答案，需要根据你的 Agent 容错程度调，踩坑记录里会展开。

---

## 二、回归测试：防止能力退化

### 2.1 前端的 Jest 类比

Shadow Testing 是上线前的"安全网"，回归测试是开发过程中的"刹车"。

回忆你做前端的流程：改一个组件 → `npm run test` → Jest 跑一堆测试用例 → 全绿才提交 PR。Agent 也一样——你改了 prompt 或加了工具，应该跑一套固定测试，确保已有功能没退化。

| 前端回归测试 | Agent 回归测试 |
|-------------|----------------|
| 测代码逻辑 | 测 Agent 行为 |
| `assert(sum(1,2)).toBe(3)` | `assert("路线" in answer)` |
| 输出是确定性数据 | 输出是自然语言 |
| Jest 跑测试 | pytest 跑测试 |
| 改了组件确保不破坏已有功能 | 改了 prompt 确保已有能力不退化 |

### 2.2 Agent 回归测试的特殊性

但 Agent 回归测试有个本质难点：**Agent 输出是自然语言，不是确定性结果。** 你不能用 `assert result == "exact string"`，因为 LLM 每次输出都可能略有不同——同一句"推荐川西路线"，可能这次说"推荐路线"，下次说"为您推荐以下路线"。

所以断言策略要变：

| 断言策略 | 写法 | 适用场景 |
|---------|------|---------|
| 关键词包含 | `assert "路线" in answer` | 答案必须提到某概念 |
| 关键词排除 | `assert "抱歉" not in answer` | 答案不该出现某些词 |
| 工具调用检查 | `assert len(tool_calls) > 0` | 该调工具时调了 |
| 长度范围 | `assert 10 < len(answer) < 500` | 答案不能太短或太长 |
| LLM-as-Judge | 让 LLM 判断答案是否合格 | 复杂语义判断 |

前四种是确定性断言（快、便宜），最后一种是非确定性断言（慢、贵但准）。实际项目里两种结合用——能确定的用关键词，复杂判断用 LLM-as-Judge。

### 2.3 测试结构

```python
"""test_agent_regression.py — Agent 回归测试"""
import pytest
from agents.main_agent import build_agent


@pytest.fixture(scope="module")
def agent():
    """整个模块共享一个 Agent 实例，省去重复初始化"""
    return build_agent()


class TestRouteSearch:
    """路线搜索功能的回归测试"""

    def test_normal_route_query(self, agent):
        """正常路线查询应该返回路线推荐"""
        result = agent.invoke({"messages": [
            {"role": "user", "content": "推荐川西3天进阶路线"}
        ]})
        answer = result["messages"][-1].content
        assert "路线" in answer or "推荐" in answer

    def test_should_call_search_tool(self, agent):
        """路线查询应该调用 search_routes 工具"""
        result = agent.invoke({"messages": [
            {"role": "user", "content": "川西有什么路线"}
        ]})
        # 检查是否调用了工具
        tool_calls = [m for m in result["messages"] if m.type == "tool"]
        assert len(tool_calls) > 0

    def test_invalid_input_handling(self, agent):
        """无效输入应该优雅处理"""
        result = agent.invoke({"messages": [
            {"role": "user", "content": "推荐999天的路线"}
        ]})
        answer = result["messages"][-1].content
        assert "无法" in answer or "不合理" in answer or "建议" in answer


class TestWeatherQuery:
    """天气查询功能的回归测试"""

    def test_normal_weather_query(self, agent):
        """正常天气查询应该返回天气信息"""
        result = agent.invoke({"messages": [
            {"role": "user", "content": "四姑娘山明天天气怎么样"}
        ]})
        answer = result["messages"][-1].content
        assert "天气" in answer or "温度" in answer or "晴" in answer

    def test_should_call_weather_tool(self, agent):
        """天气查询应该调用 get_weather 工具"""
        result = agent.invoke({"messages": [
            {"role": "user", "content": "川西下周天气"}
        ]})
        tool_calls = [m for m in result["messages"] if m.type == "tool"]
        assert len(tool_calls) > 0
```

测试结构要点：

- 按功能分 `class`（TestRouteSearch、TestWeatherQuery），每个 class 测一个功能模块
- 测试方法名描述清楚测什么（test_normal_route_query 而不是 test1）
- `@pytest.fixture(scope="module")` 让 Agent 只初始化一次，所有测试共享——Agent 初始化慢，每次都建新的会很慢

### 2.4 测试用例设计：覆盖正常 + 异常 + 边界

好的回归测试要覆盖三类场景，和前端测试设计思路一样：

```
正常路径（Happy Path）  → "推荐川西3天路线" → 应该返回路线
异常路径（Error Path）  → "推荐999天的路线" → 应该优雅拒绝
边界路径（Edge Case）   → "路线"（输入太短）→ 应该请求澄清
```

```python
class TestEdgeCases:
    """边界情况测试"""

    def test_empty_input(self, agent):
        """空输入应该有兜底响应"""
        result = agent.invoke({"messages": [
            {"role": "user", "content": ""}
        ]})
        answer = result["messages"][-1].content
        assert len(answer) > 0  # 不能返回空

    def test_ambiguous_input(self, agent):
        """模糊输入应该请求澄清"""
        result = agent.invoke({"messages": [
            {"role": "user", "content": "路线"}
        ]})
        answer = result["messages"][-1].content
        # 应该问用户更多信息，而不是瞎推荐
        assert "请问" in answer or "具体" in answer or "哪条" in answer
```

跑测试：`pytest tests/ -v`（失败时加 `--tb=short` 看简短 traceback，加 `-s` 显示 print）。如果改了 prompt 导致某个测试从 PASSED 变成 FAILED，立刻就知道改坏了哪里——这就是回归测试的价值。

---

## 三、CI 集成：GitHub Actions 自动测试

### 3.1 从手动到自动

到目前为止你的流程是：改 Agent → 手动 `pytest tests/ -v` → 看结果。问题：容易忘（改完忘了跑测试就提交）、协作时别人不知道要跑哪些测试、PR 合并前没人检查测试是否通过。

解决方案：**把回归测试集成到 GitHub Actions，每次 push 自动跑。** 这就是 CI（持续集成）。

> **前端类比：** 你做前端肯定配过 GitHub Actions——每次 push 自动跑 `npm run test` 和 `npm run build`，PR 检查不通过不让合并。Agent 的 CI 完全一样，只是把 `npm run test` 换成 `pytest tests/ -v`。前端经验直接迁移过来。

### 3.2 配置文件

GitHub Actions 的配置文件放在 `.github/workflows/` 目录下，YAML 格式：

```yaml
# .github/workflows/agent-tests.yml
name: Agent Regression Tests

on:
  push:
    paths:
      - 'agents/**'
      - 'tools/**'
      - 'tests/**'
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - run: pip install pytest
      - name: Run Agent Tests
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
        run: pytest tests/ -v --tb=short
```

逐行解释：

| 配置项 | 作用 |
|--------|------|
| `on.push.paths` | 只有改了 agents/tools/tests 目录才触发，避免改文档也跑测试 |
| `on.pull_request.branches` | PR 合并到 main 前必须跑测试 |
| `runs-on: ubuntu-latest` | 用 GitHub 提供的 Ubuntu 机器跑 |
| `actions/checkout@v4` | 拉取你的代码 |
| `actions/setup-python@v5` | 安装 Python 3.11 |
| `env.OPENAI_API_KEY` | 从 GitHub Secrets 读取密钥 |
| `pytest tests/ -v --tb=short` | 跑测试 |

### 3.3 API Key 管理：用 Secrets

注意配置里这行：

```yaml
env:
  OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
```

这里用 `secrets.OPENAI_API_KEY`，不是直接写明文 key。GitHub Secrets 是加密存储的，只有 Actions 运行时能解密，日志里也不会打印出来。

**绝对不要把 API Key 写在代码里或配置文件里提交到 Git！** 前端项目里你可能见过 `.env` 文件被误提交导致 key 泄露的事故，Agent 项目更要注意——你的 key 能调 LLM，泄露了会被刷爆账单。

设置 Secrets：GitHub 仓库 → Settings → Secrets and variables → Actions → New repository secret → Name 填 `OPENAI_API_KEY`，Value 填你的 key → Add secret。

### 3.4 CI 触发条件与执行流程

`on.push.paths` 的设计很关键——不是每次 push 都跑测试，只在改了相关代码时才跑：

```yaml
on:
  push:
    paths:
      - 'agents/**'      # 改了 Agent 代码
      - 'tools/**'       # 改了工具代码
      - 'tests/**'       # 改了测试代码
      - 'requirements.txt'      # 改了依赖
      - '.github/workflows/**'  # 改了 workflow 本身
  pull_request:
    branches: [main]     # PR 到 main 必跑
```

这样改 README 文档不会触发测试，省 token 省 CI 额度。Agent 测试每次跑都消耗 LLM token，不像前端 Jest 跑测试基本不花钱，所以触发条件要克制。整个执行流程和前端 CI 一样：

```
你改了 Agent 代码 → git push → GitHub 收到 push
   → 检查 paths 是否匹配 → 不匹配则跳过
   → 匹配则启动 Actions：checkout → 装 Python → 装依赖 → 跑 pytest
   → 全绿 → 绿色对勾，PR 可合并
   → 有失败 → 红色叉号，PR 阻塞，通知你修
```

### 3.5 进阶：CI 里加质量门槛

光跑测试通过还不够，你还可以在 CI 里加质量门槛——把 Day 03 的 RAGAS 分数也纳入 CI：

```yaml
- name: Run RAGAS Quality Gate
  env:
    OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
  run: |
    python scripts/rag_eval.py --threshold 0.7
    # 脚本里如果 faithfulness < 0.7 就 sys.exit(1)，让 CI 失败
```

这样 CI 不只检查"功能没退化"，还检查"质量没下降"。把 Day 01-03 的评估指标、今天的回归测试串成一条线：评估发现问题 → 回归测试防退化 → CI 自动执行，整个质量保障闭环就形成了。

---

## 动手实验

### 🟢 青铜：写 3 个回归测试用例，用 pytest 本地运行

1. 安装 pytest：`pip install pytest`
2. 在 `tests/test_agent_regression.py` 写 3 个测试用例（参考 2.3 的代码）
3. 用你 Week 06-07 搭的 Agent 跑测试
4. 本地运行 `pytest tests/ -v`，确保全绿
5. 故意改坏一个 prompt（比如把"路线推荐"改成"天气查询"），看测试是不是变红

目标：体会"改了 Agent → 跑测试 → 测试告诉你哪里坏了"的反馈循环。

### 🟡 白银：完成 shadow_test.py — 新旧 prompt 版本的 Shadow Testing

1. 准备两版 Agent：旧版用 Week 06 的 prompt，新版用 Day 03 Promptfoo 选出的更优 prompt
2. 实现 `shadow_test.py`（参考 1.3 的代码框架）
3. 实现 `compare_results`（参考 1.4，用 embedding 相似度）
4. 准备 10 个测试任务，跑 Shadow Testing
5. 输出差异度报告，判断新版本能不能上线
6. 把结果保存到 `shadow_test_result.json`

```python
# 白银实验的报告格式示例
{
  "avg_diff_score": 0.08,
  "recommendation": "可上线",
  "details": [
    {"task": "t1", "diff_score": 0.05, "diff_type": "minor"},
    {"task": "t2", "diff_score": 0.12, "diff_type": "minor"},
    {"task": "t3", "diff_score": 0.23, "diff_type": "major",
     "note": "新版本没调用工具"}
  ]
}
```

### 🔴 王者：配置 GitHub Actions，让回归测试在每次 push 时自动运行

1. 在仓库创建 `.github/workflows/agent-tests.yml`
2. 配置触发条件（on.push.paths）
3. 把 OPENAI_API_KEY 配到 GitHub Secrets
4. push 一次代码，观察 Actions 是否自动跑测试
5. 故意改坏一个测试用例让它失败，看 CI 是否标红、PR 是否被阻塞
6. 修复后 push，看 CI 变绿
7. （加分项）在 CI 里加 RAGAS 质量门槛（参考 3.5）

目标：让你的 Agent 项目拥有和前端项目一样的 CI 体验——改了代码自动跑测试，PR 检查通过才能合并。

---

## 踩坑记录 🕳️

### 坑 1：Agent 回归测试消耗 token，CI 跑一次可能花几美元

和 Day 03 的 RAGAS 一样，Agent 回归测试每次都真实调用 LLM——每个测试用例至少一次 invoke，加上 LLM-as-Judge 还要额外调 LLM。10 个测试用例跑一轮，可能消耗几万 token。

**问题：** CI 每次 push 都跑，一天 push 十几次，token 账单可能很吓人。

**解决：**
- 测试用例数量控制——回归测试不追求覆盖所有场景，抓核心路径（10-20 个够用）
- CI 触发条件克制——只在改了 agents/tools/tests 才跑，改文档不跑
- 用便宜模型跑测试——gpt-4o-mini 而不是 gpt-4，测试断言通常不要求高质量输出
- 大改动用 Shadow Testing 离线跑，小改动才走 CI

### 坑 2：LLM 输出的不确定性导致测试偶尔 flaky（不稳定）

这是 Agent 测试和前端测试最大的不同。前端 `sum(1,2)` 永远等于 3，但 Agent 同一个输入跑两次，输出可能不完全一样——有时通过断言，有时不通过。这种"时好时坏"的测试叫 flaky test。

**问题：** CI 偶尔红，但本地跑又绿，搞不清是真 bug 还是 flaky。

**解决：**
- 断言用宽松条件——用"包含关键词"而不是"完全相等"
- 避免对 LLM 输出格式做精确断言（如"必须正好 3 行"）
- flaky 的测试加重试机制：`@pytest.mark.flaky(reruns=3)`（需装 pytest-rerunfailures）
- 对 flaky 测试加标记，CI 里单独处理，不让它阻塞主流程

```python
# pytest-rerunfailures 的用法
@pytest.mark.flaky(reruns=3, reruns_delay=2)
def test_llm_output(self, agent):
    """这个测试因为 LLM 不确定性，允许重试 3 次"""
    result = agent.invoke({"messages": [...]})
    # ...
```

### 坑 3：Shadow Testing 的对比指标不好定（什么算"差异大"）

什么算"差异大"？0.1？0.2？0.3？没有标准答案。

**问题：** 阈值定低了，明明有退化却判为"可上线"；定高了，正常的输出波动也被判为"差异大"。

**解决：**
- 先用现有生产版本自己和自己对比（新旧都是旧版），看自然差异度是多少——这就是 baseline
- 阈值设为 baseline 的 1.5-2 倍
- 不要只看平均差异度，看有没有个别 case 差异特别大——平均没问题但某个 case 退化严重，也要警惕
- 结合 LLM-as-Judge 做语义判断，关键词重合度只做初筛

### 坑 4：CI 中的 API Key 管理要用 secrets

前面 3.3 强调过，再啰嗦一遍——这是最容易出事的地方。

**常见错误：**
- 把 `.env` 文件提交到 Git（即使 .gitignore 忘了加）
- 在 yaml 里直接写 `OPENAI_API_KEY: sk-xxxx`
- Fork 的仓库忘了配 secrets，CI 直接失败

**解决：**
- `.env` 加入 `.gitignore`
- 永远用 `${{ secrets.XXX }}` 引用
- CI 失败提示 `KeyError: OPENAI_API_KEY` 时，先检查仓库的 Secrets 有没有配
- 给 CI 用的 key 设额度上限（OpenAI 后台能设 monthly spending limit），防泄露被刷爆

---

## 副线笔记

### 用 Claude Code 写回归测试脚本

今天的副线是：用 Claude Code 根据 Agent 的功能自动生成测试用例骨架，你补充断言逻辑，对比手写 vs AI 辅助的效率。

**手写测试的痛点：** 要逐个想测试场景（正常/异常/边界），每个场景都要写 invoke + 断言，模板代码重复，容易漏掉边界 case。

**用 Claude Code 的方式：** 你给 Claude Code 看 Agent 代码（`agents/main_agent.py`）和它的工具清单（search_routes、get_weather），让它生成测试骨架——它会自动列出 TestRouteSearch（正常查询、调工具、无效输入）、TestWeatherQuery、TestEdgeCases（空输入、模糊输入）等 class，每个用例的断言部分留 TODO 让你填。你只需补充断言逻辑（`assert "路线" in answer` 之类的）。

**效率对比：** 纯手写 10 个用例约 1 小时，Claude Code 辅助约 15 分钟，且 AI 会主动覆盖正常/异常/边界三类，不容易漏 case。但 AI 生成的断言可能过于宽松（啥都通过）或过于严格（动不动就失败），断言的"松紧度"是测试设计的核心，AI 给的是初稿，你要根据实际业务调。

> 这和前端用 AI 生成 Jest 测试一个道理——AI 帮你搭脚手架，断言的"度"还得人来定。好的测试不是"能通过"，而是"该通过时通过、该失败时失败"。

---

## 检查清单

- [ ] 理解 Shadow Testing 的原理（新旧并行、新版本只记录不返回）
- [ ] 写了 Agent 回归测试（用 pytest，覆盖正常/异常/边界）
- [ ] 配置了 GitHub Actions，让回归测试在每次 push 时自动运行
- [ ] 用 GitHub Secrets 管理 API Key
- [ ] 知道怎么防止 Agent 改动后退化（Shadow Testing + 回归测试 + CI 三道防线）

---

## 下课预告

> **Day 05 — 安全：Prompt Injection 防御 + Tool Abuse。** 今天我们解决了"改了 Agent 不退化"的问题——Shadow Testing 是上线前的安全网，回归测试是开发中的刹车，CI 是自动化的守门员，三道防线一起保障 Agent 质量。但还有一种"退化"不是"功能退化"，而是"被攻击退化"——用户故意用 prompt injection 让你的 Agent 偏离指令，或者诱导它滥用工具（比如删库）。明天学安全防御，先从最常见的 Prompt Injection 开始：用户怎么在输入里注入恶意指令、Agent 怎么被带偏、怎么防。再讲 Tool Abuse——Agent 该不该有删数据的权限、怎么用 Human-in-the-loop 把关危险操作。
