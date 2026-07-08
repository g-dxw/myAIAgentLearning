# Day 03 — Reflection/Self-Correction 模式

## 学习目标

Day 02 我们搭了提取 Agent——把护工的微信录音转成结构化的护理记录表单。但提取 Agent 不是万能的，它会犯错：体温 36.8 抄成 38.6、血压漏填了收缩压、明明老人说"今天有点头晕"却没标异常。这些问题如果直接进数据库，后续的趋势分析、异常告警全得跟着出错。今天要学的 Reflection 模式，就是给提取结果加一道"复审"——让另一个 Critic Agent 检查输出，发现问题反馈给提取 Agent 修正，直到"够好"为止。

这是面试 Q8 的高频考点。面试官最爱问"你的 Agent 输出错了怎么办"，标准答案就是 Reflection。但 2026 年的实现方式有了新选择：除了经典的 StateGraph 双节点循环，官方还推荐用 `create_agent` + `RubricGradingMiddleware` 做 LLM-as-Judge 自评迭代。今天两种都会讲，代码用 StateGraph 因为更直观易懂，但你要知道 Middleware 方式才是 2026 的"官方推荐姿势"。

学完今天你能：

1. 理解 Reflection/Self-Correction 的本质：Agent 生成输出后，另一个 Agent（或同一个）扮演 Critic 检查，反馈迭代直到"够好"
2. 能用经典 StateGraph 方式实现 reflection_agent.py：generation_node + reflection_node + 条件边循环
3. 知道 2026 官方推荐的 create_agent + RubricGradingMiddleware 做法，能说清两种方式的差异和选型
4. 能回答面试 Q8"Agent 输出错了怎么办"——用 Code Review 的类比讲清 Reflection 的价值

---

## 一、什么是 Reflection/Self-Correction

### 1.1 定义与 Code Review 类比

Reflection 模式的核心思路是：**Agent 生成输出后，不直接交付，而是先让一个 Critic（审查者）检查，发现问题反馈给生成者修正，循环迭代直到"够好"才输出。**

理解它最好的类比就是前端工程师天天做的 Code Review：

```
你写完代码（生成输出）→ 提交 PR → Reviewer 检查（Critic 审查）
    ├─ 通过 → 合并到主分支（交付输出）✅
    └─ 有问题 → 留 review 评论（反馈）→ 你改代码再提交 → Reviewer 再查 → ...
```

| Code Review 环节 | Reflection 模式环节 |
|------------------|-------------------|
| 你写代码 | generation_node 生成提取结果 |
| 提交 PR | draft 写入 State |
| Reviewer 检查 | reflection_node 审查 |
| 留 review 评论 | critique 反馈写入 State |
| 你改代码再提交 | 重新跑 generation_node |
| Reviewer 通过 | 条件边判断 PASS → END |
| review 太多次还没过 | 达到 max_iterations 强制结束 |

你不会写完代码直接 merge 到主分支——那是裸奔。同理，Agent 也不该生成完直接交付。Reflection 就是给 Agent 的输出加了 Code Review 这道工序。

三个关键词要注意：**Critic** 可以是另一个 Agent（外反思，生产推荐）或同一个 Agent 换身份（自反思）；**反馈迭代** 是给具体反馈而非"重试"——"血压漏了收缩压"比"再来一次"有用得多；**"够好"为止** 要有终止条件，否则死循环。

### 1.2 Reflection 不是简单的重试

重试（retry）是无脑再来一次，Reflection 是**带着反馈的定向修正**：

```
重试：跑一遍 → 结果不行 → 原样再跑一遍 → 期望这次运气好点（没有信息传递）
Reflection：跑一遍 → Critic 检查 → "血压漏了，体温38.6要标异常" → 带反馈修正（有信息传递）
```

> **前端类比：** 重试就像你提交代码被拒了，啥也没改又提交一次——大概率还是被拒。Reflection 是你看了 review 评论，针对性改了再提交——通过概率高得多。

---

## 二、为什么养老场景需要 Reflection

### 2.1 提取 Agent 会犯三类错

Day 02 的提取 Agent 把这段录音转成表单：

```
护工录音（ASR 转写后）：
"今天给王奶奶量了体温，36度8，血压高压135低压85，
 她说今天有点头晕，吃饭还行，精神不太好。"
```

提取 Agent 实际可能犯这三类错：

**第一类：字段填错** — "36度8" → temperature 填成 38.6（小数点看错位）。格式没问题，Pydantic 校验也过（都在合理范围），但数值层发现不了。

**第二类：字段遗漏** — 录音里说了"精神不太好"，但 mental_status 字段为空；"她说今天有点头晕" → symptoms 漏了。遗漏比填错更危险——下游趋势分析发现不了"精神状态在下降"。

**第三类：异常没标记** — 体温 38.6 超过 37.3 应该标 is_abnormal=true，但没标；"头晕"应该标异常，但没标。这是最致命的——养老场景里"异常没标记"可能延误老人的病情发现。

### 2.2 Pydantic 校验挡不住语义错误

你可能会问：不能在 Pydantic 模型里加校验规则吗？答案是**能挡住格式错误，挡不住语义错误**。

- Pydantic 能挡：体温填成 380（超范围）、必填字段为空
- Pydantic 挡不住：36.8 填成 38.6（都在合理范围）、"头晕"症状遗漏、异常没标记（它不懂业务规则）

**规则校验查的是"格式对不对"，Reflection 查的是"内容对不对、全不全、合不合业务逻辑"。** 前者是结构层，后者是语义层。养老场景对语义正确性要求极高——一个遗漏的异常可能关系到老人健康，所以必须有 Reflection 这道语义复审。

### 2.3 Reflection 在系统里的位置

```
护工录音 → ASR 语音转文本（Day 01）→ 提取 Agent 初步表单（Day 02）
   │
   ▼
┌─────────────────────────────────────┐
│  Reflection 复审（Day 03 今天学的）    │
│  提取结果 → Critic 检查 → 通过？       │
│      ├─ 是 → 输出                     │
│      └─ 否 → 反馈 → 修正 → 再检查     │
└─────────────────────────────────────┘
   │
   ▼
写入数据库（后续 Day 04-06 趋势分析、通知）
```

---

## 三、两种实现方式：StateGraph vs Middleware

### 3.1 2026 年的两条路

| 维度 | 经典 StateGraph 双节点循环 | create_agent + Middleware |
|------|--------------------------|--------------------------|
| 思路 | 手动搭 generation_node + reflection_node，条件边控制循环 | 把"审查+反馈"封装成 Middleware，挂到 Agent 上自动跑 |
| 控制力 | 高（循环逻辑全你写） | 低（内部封装，只配 rubric） |
| 透明度 | 高（每轮 draft/critique 可见可调试） | 低（黑盒，内部循环看不到细节） |
| 2026 定位 | 教学首选，理解原理 | 官方推荐，生产快搭 |

### 3.2 经典 StateGraph 双节点循环

核心是定义两个节点，用条件边串成循环：

```
START → generation_node → reflection_node → should_continue?
                                              ├─ PASS → END
                                              └─ FAIL → 回到 generation_node
```

- **generation_node**：调 `create_agent` 做提取，输出 draft（草稿）。后续轮带着 critique 做定向修正
- **reflection_node**：调 LLM 扮演 Critic 审查 draft，输出 critique（审查意见）和 pass/fail 判定
- **should_continue**：条件边函数，读 critique 判断 PASS（够好了）还是 FAIL（还得改）

优点是**完全透明**——每一轮的 draft、critique 都存在 State 里，你能看到"第 1 轮提取了什么、Critic 怎么批评的、第 2 轮改成了什么"。

### 3.3 create_agent + RubricGradingMiddleware

2026 年 LangChain 官方推荐做法。把"审查+反馈"封装成 Middleware，Agent 生成完自动触发评分循环：

```python
from langchain.agents import create_agent
from deepagents import RubricGradingMiddleware

rubric_middleware = RubricGradingMiddleware(
    model="anthropic:claude-haiku-4-5",  # 评分模型，可用更便宜的
    system_prompt="你是护理记录质检员，逐条检查 rubric...",
    tools=[check_vital_ranges],          # 评分工具，获取硬证据
    max_iterations=3,                     # 最大修正轮次
)
agent = create_agent(model="anthropic:claude-sonnet-4-6", middleware=[rubric_middleware])
result = agent.invoke({
    "messages": [HumanMessage(content="护工录音...")],
    "rubric": "- 体温必须与原文一致\n- 血压必须有收缩压和舒张压\n- 有症状时 is_abnormal 必须为 true",
})
```

工作流程：Agent 生成 → Grader（独立子 Agent）按 rubric 逐条评分 → 全过则交付，有未过项则把逐条反馈注入对话让 Agent 重新生成 → 循环到全过或 max_iterations。关键设计是**评分由独立的子 Agent 完成**，不是主 Agent 自评自夸——能用更便宜的模型，还能调工具验证硬数据。

### 3.4 为什么今天代码用 StateGraph

两种都讲清楚后，今天的主代码用 StateGraph：一是教学化，每一步状态透明能看清 Critic 怎么反馈、Agent 怎么改；二是可控性，养老场景审查规则复杂（完整性/一致性/异常标记三维），能精确控制；三是可调试，出问题时 State 里存了每轮 draft 和 critique，能精确定位哪轮哪个维度没通过。

> **前端类比：** StateGraph 就像手动搭 CI 流水线——每个 step（lint、test、build）自己写，能看每步日志。Middleware 就像用 GitHub Actions——配个 yaml 就跑，但内部细节看不到。学原理用手动，上生产用平台。

---

## 四、Reflection 循环图

```
护工录音（ASR 文本）
   │
   ▼
┌──────────────────────────────────────────────────────────┐
│  generation_node（提取 Agent）                            │
│  输入：录音文本 + 上一轮的 critique（首轮没有）              │
│  输出：draft（结构化表单草稿）                              │
│  逻辑：调 create_agent 做提取，如果有 critique 就按反馈修正  │
└──────────────────────────────────────────────────────────┘
   │  draft 写入 State
   ▼
┌──────────────────────────────────────────────────────────┐
│  reflection_node（Critic Agent）                          │
│  输入：录音文本 + draft                                    │
│  输出：critique（审查意见）+ passed（是否通过）             │
│  逻辑：调 LLM 检查 完整性/一致性/异常标记 三维              │
└──────────────────────────────────────────────────────────┘
   │  critique 写入 State, pass_count + 1
   ▼
┌──────────────────────────────────────────────────────────┐
│  should_continue（条件边函数）                             │
│    passed == True ? → END（输出最终 draft）       ✅       │
│    pass_count >= max_iterations ? → END（强制输出）⚠️     │
│    否则 → 路由回 generation_node（带 critique）            │
└──────────────────────────────────────────────────────────┘
```

一次完整迭代示例（"王奶奶"录音）：

```
=== 第 1 轮 ===
generation_node 输出 draft：
  temperature: 38.6        ← 错！原文是 36.8
  symptoms: []              ← 遗漏！原文有"头晕"
  is_abnormal: false        ← 错！38.6 + 头晕 都该标异常

reflection_node 审查 critique：
  "未通过。发现 3 个问题：
   1. [一致性] temperature=38.6 与原文'36度8'不符，应为 36.8
   2. [完整性] 原文'头晕'未提取到 symptoms
   3. [异常标记] 体温>37.3 且有症状，is_abnormal 应为 true"

should_continue: passed=False, pass_count=1 < max=3 → 回 generation_node

=== 第 2 轮 ===
generation_node 输出 draft（按 critique 修正）：
  temperature: 36.8         ← 修正了
  symptoms: ["头晕"]          ← 补上了
  is_abnormal: true          ← 修正了

reflection_node 审查 critique：
  "通过。完整性/一致性/异常标记三维全部通过。"

should_continue: passed=True → END ✅
```

第 1 轮 Critic 发现 3 个问题，第 2 轮 Agent 带着"具体哪 3 个问题、该怎么改"的反馈精准修正，一次就过了。这就是 Reflection 比无脑重试强的地方——**反馈是定向的，修正是有依据的**。

---

## 五、完整代码：reflection_agent.py

```python
"""reflection_agent.py — Reflection/Self-Correction 模式

养老护工智能记录系统 Day 03 产出
用经典 StateGraph 双节点循环实现提取结果的自纠错复审

依赖（2026 版本）：pip install langchain langgraph
"""
from langchain.agents import create_agent
from langchain.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langchain.chat_models import init_chat_model
from langgraph.graph import StateGraph, END, START
from langchain_core.messages import HumanMessage, SystemMessage
from typing import TypedDict, Annotated
import operator
import json


class GenerationState(TypedDict):
    """Reflection 循环的状态机，每个 key 跨节点传递"""
    recording_text: str       # 原始录音文本（全程不变）
    draft: str                # 提取结果草稿，每轮 generation_node 更新
    critique: str             # Critic 审查意见，每轮 reflection_node 更新
    passed: bool              # 是否通过审查
    pass_count: int           # 已迭代轮数，防死循环
    messages: Annotated[list, operator.add]  # 对话上下文（累加）


EXTRACTION_PROMPT = """你是养老护理记录提取助手。
根据护工的录音文本，提取结构化的护理记录，输出 JSON。
字段：patient_name, temperature(浮点), blood_pressure_systolic(整数),
blood_pressure_diastolic(整数), symptoms(列表), appetite, mental_status, is_abnormal(布尔)。
体温>37.3 或有症状 或 精神欠佳 时 is_abnormal 为 true。只输出 JSON。"""


def generation_node(state: GenerationState) -> dict:
    """提取节点：调 LLM 生成/修正 draft。首轮纯提取，后续轮带 critique 修正"""
    recording_text = state["recording_text"]
    critique = state.get("critique", "")
    pass_count = state.get("pass_count", 0)

    if pass_count == 0:
        user_content = f"护工录音：\n{recording_text}\n\n请提取护理记录。"
    else:
        # 后续轮：带着 Critic 的反馈做定向修正
        user_content = (
            f"护工录音：\n{recording_text}\n\n"
            f"你上一轮的提取结果被质检员发现以下问题：\n{critique}\n\n"
            f"请根据这些问题修正，重新输出完整的护理记录 JSON。"
        )

    model = init_chat_model("openai:gpt-4o-mini")
    response = model.invoke([
        SystemMessage(content=EXTRACTION_PROMPT),
        HumanMessage(content=user_content),
    ])
    return {"draft": response.content, "messages": [response]}


CRITIC_PROMPT = """你是养老护理记录质检员，从三个维度检查提取结果：
1. 完整性：所有字段是否已填写？原文提到的症状是否都提取了？
2. 一致性：数值是否与原文一致？体温有没有抄错位？
3. 异常标记：体温>37.3 或有症状时 is_abnormal 是否为 true？
输出 JSON：{"passed": true/false, "issues": ["问题1", "问题2"], "suggestion": "修正建议"}
只有三个维度全部通过才设 passed=true。"""


def reflection_node(state: GenerationState) -> dict:
    """审查节点：Critic 检查 draft，输出 critique 和 passed"""
    recording_text = state["recording_text"]
    draft = state["draft"]

    model = init_chat_model("openai:gpt-4o-mini")
    response = model.invoke([
        SystemMessage(content=CRITIC_PROMPT),
        HumanMessage(content=(
            f"护工录音原文：\n{recording_text}\n\n"
            f"提取结果（待审查）：\n{draft}\n\n请按三个维度检查，输出 JSON。"
        )),
    ])

    # 解析 Critic 的 JSON 输出
    try:
        result = json.loads(response.content)
        passed = result.get("passed", False)
        issues = result.get("issues", [])
        suggestion = result.get("suggestion", "")
        critique = (f"问题列表：{issues}\n修正建议：{suggestion}"
                    if not passed else "所有检查通过")
    except json.JSONDecodeError:
        # LLM 输出不是合法 JSON，保守判为不通过
        passed = False
        critique = f"质检输出解析失败，原文：{response.content}"

    return {
        "critique": critique,
        "passed": passed,
        "pass_count": state.get("pass_count", 0) + 1,
        "messages": [response],
    }


MAX_ITERATIONS = 3  # 最大迭代次数，防死循环


def should_continue(state: GenerationState) -> str:
    """条件边函数：通过→end，超限→end，否则→generate"""
    if state["passed"]:
        return "end"                          # Critic 判定通过 → 输出
    if state["pass_count"] >= MAX_ITERATIONS:
        print(f"⚠️ 达到最大迭代 {MAX_ITERATIONS} 次，强制输出")
        return "end"                          # 达到上限，强制输出
    return "generate"                         # 带 critique 回去修正


def build_reflection_graph():
    """组装 StateGraph：START → generate → reflect → should_continue?
                                       ├─ "end" → END
                                       └─ "generate" → generate（循环）"""
    graph = StateGraph(GenerationState)
    graph.add_node("generate", generation_node)
    graph.add_node("reflect", reflection_node)
    graph.add_edge(START, "generate")
    graph.add_edge("generate", "reflect")
    graph.add_conditional_edges("reflect", should_continue,
                                {"end": END, "generate": "generate"})
    checkpointer = InMemorySaver()
    return graph.compile(checkpointer=checkpointer)


def run_reflection(recording_text: str) -> dict:
    """运行 Reflection 循环，返回最终提取结果 + 迭代信息"""
    app = build_reflection_graph()
    initial_state = {
        "recording_text": recording_text, "draft": "", "critique": "",
        "passed": False, "pass_count": 0, "messages": [],
    }
    config = {"configurable": {"thread_id": "care-record-001"}}
    final_state = app.invoke(initial_state, config=config)
    return {
        "final_draft": final_state["draft"],
        "critique": final_state["critique"],
        "passed": final_state["passed"],
        "iterations": final_state["pass_count"],
    }


if __name__ == "__main__":
    recording = ("今天给王奶奶量了体温，36度8，血压高压135低压85，"
                 "她说今天有点头晕，吃饭还行，精神不太好。")
    result = run_reflection(recording)
    print(f"迭代轮数: {result['iterations']}  通过: {result['passed']}")
    print(f"最终提取结果:\n{result['final_draft']}")
    print(f"审查意见:\n{result['critique']}")
```

> 注意 2026 年的 import 路径：`create_agent` 从 `langchain.agents` 来，`init_chat_model` 从 `langchain.chat_models` 来，`InMemorySaver` 从 `langgraph.checkpoint.memory` 来。别用过时的 `from langchain.agents import initialize_agent`。

State 里 `messages` 用 `Annotated[list, operator.add]` 标注——意味着每个节点返回的 messages 会**累加**而非覆盖，这样 generation_node 第二轮能看到第一轮的 critique。generation_node 第 2 轮会把上一轮的 `critique` 拼进 prompt——"你上一轮的结果被质检员发现这些问题：...请修正"。这就是 Reflection 的精髓：**修正不是盲目重跑，而是带着具体反馈的定向修正**。

---

## 六、Critic Agent 的 system_prompt 设计

Critic 的核心是它的 system_prompt。养老场景要检查三个维度，缺一不可：

| 维度 | 查什么 | 例子 |
|------|--------|------|
| **完整性** | 字段有没有漏填？原文信息有没有提取？ | "精神不太好"漏提取到 mental_status |
| **一致性** | 数值和原文对不对得上？有没有抄错位？ | 36.8 抄成 38.6 |
| **异常标记** | 该标异常的有没有标？业务规则对不对？ | 体温>37.3 或有症状时 is_abnormal 要为 true |

三个维度的具体检查项：

```
【完整性】1.所有必填字段已填写 2.原文症状都提取到 symptoms 3.原文食欲/精神状态已提取
【一致性】1.体温数值与原文一致（36度8→36.8，非38.6）
          2.血压数值与原文一致且收缩压/舒张压没搞反 3.字段类型正确（体温float/血压int）
【异常标记】体温>37.3→异常 | 有症状→异常 | 精神欠佳→异常 | 血压>140/90→异常
          反之：全正常→is_abnormal应为false（不能过度告警）
```

> **前端类比：** 这三个维度就像前端表单校验的三层。完整性是 `required` 校验（必填项），一致性是自定义校验（"两次密码要一致"），异常标记是业务规则校验（"金额超过 10000 要二次确认"）。Pydantic 能做前两层的一部分，第三层业务规则只能靠 Critic 的语义理解。

---

## 七、2026 官方推荐：RubricGradingMiddleware

前面主代码用了 StateGraph，这里补上 2026 官方推荐的 Middleware 做法：

```python
"""reflection_middleware.py — 2026 官方推荐的 Middleware 方式
对比 StateGraph：更简洁，但内部循环是黑盒"""
from langchain.agents import create_agent
from langchain.tools import tool
from langchain_core.messages import HumanMessage
from deepagents import RubricGradingMiddleware


@tool
def check_vital_ranges(temperature: float, systolic: int, diastolic: int) -> str:
    """检查生命体征数值是否在合理范围内"""
    issues = []
    if temperature > 37.3:
        issues.append(f"体温 {temperature}℃ 偏高，应标记异常")
    if systolic > 140 or diastolic > 90:
        issues.append(f"血压 {systolic}/{diastolic} 偏高，应标记异常")
    return "; ".join(issues) if issues else "生命体征数值正常"


rubric_middleware = RubricGradingMiddleware(
    model="anthropic:claude-haiku-4-5",  # 评分模型，可更便宜
    system_prompt="你是养老护理记录质检员，逐条检查 rubric，可调用 check_vital_ranges 验证数值。",
    tools=[check_vital_ranges],   # 评分工具，获取硬证据
    max_iterations=3,
)
agent = create_agent(model="anthropic:claude-sonnet-4-6", middleware=[rubric_middleware])

result = agent.invoke({
    "messages": [HumanMessage(content="护工录音：今天给王奶奶量了体温，36度8...请提取 JSON。")],
    "rubric": (
        "- 体温数值必须与原文一致\n"
        "- 血压必须同时有收缩压和舒张压\n"
        "- 原文症状必须提取到 symptoms\n"
        "- 有症状时 is_abnormal 必须为 true\n"
    ),
})
```

两种方式对比选型：

| 维度 | StateGraph 双节点循环 | RubricGradingMiddleware |
|------|---------------------|------------------------|
| 代码量 | 多（要写 State/节点/边） | 少（配个 rubric 字符串） |
| 透明度 | 高（每轮 draft/critique 可见） | 低（内部循环黑盒） |
| 反馈粒度 | 自定义 Critic prompt 控制 | 逐条 per-criterion（更标准） |
| 适用 | 复杂审查逻辑、教学 | 快速上线、标准评分 |

一句话：**要理解原理、精确控制审查逻辑 → StateGraph；要快速上线、用标准评分模式 → Middleware**。生产可结合——Middleware 做日常评分，关键场景用 StateGraph 精确控制。

> **面试加分项：** 面试时主动提一句"2026 年 LangChain 官方推 RubricGradingMiddleware，评分由独立子 Agent 完成，能调工具获取硬证据，不是主 Agent 自评自夸"。这句话能证明你跟进了最新实践。

---

## 八、面试 Q8 回答模板

> **Q8：Agent 的输出可能出错，你怎么保证质量？说说 Reflection/Self-Correction 模式。**

**30 秒版：**

"Agent 输出错了我会用 Reflection 模式处理。核心是给 Agent 加一道'复审'——生成结果后不直接交付，让一个 Critic Agent 检查，发现问题反馈给生成者定向修正，循环到'够好'为止。这就像前端的 Code Review——你写完代码，Reviewer 检查，有问题退回改，通过才合并。实现上 2026 年有两条路：经典做法用 StateGraph 搭 generation_node + reflection_node 双节点循环；官方新推荐用 create_agent + RubricGradingMiddleware，让独立子 Agent 按 rubric 逐条评分。关键设计是评分由独立子 Agent 完成，能用更便宜的模型，还能调工具验证硬数据。"

**完整版（可展开 2-3 分钟）：**

1. **是什么**：Reflection 让 Agent 对自己输出做复审。生成后 Critic 检查，反馈给生成者修正，循环到通过。和重试的区别——重试是无脑再跑，Reflection 是带着具体反馈做定向修正。
2. **为什么需要**：提取 Agent 会犯三类错：字段填错（36.8 抄成 38.6）、字段遗漏（症状没提取）、异常没标记。Pydantic 只校验格式，校验不了语义。养老场景漏标异常可能延误病情，所以必须有语义层复审。
3. **怎么实现**：2026 年两种方式。StateGraph 双节点循环——generation_node 提取、reflection_node 审查、条件边控制迭代，每步透明可调试。RubricGradingMiddleware——配个 rubric 字符串自动跑循环，评分由独立子 Agent 完成，能用更便宜模型还能调工具。
4. **踩过的坑**：Critic 和生成者同模型容易"互相包庇"；没设 max_iterations 会死循环；Critic 自己也会漏判，复杂场景要多维度交叉检查。

**三句金句：**

> "Reflection 就像 Code Review——你写完代码不会直接 merge，得让 Reviewer 看过。Agent 也一样，生成完不能直接交付。"

> "重试是'原样再跑一遍碰运气'，Reflection 是'带着反馈定向修正'。区别在于反馈有没有被利用。"

> "2026 官方推荐 RubricGradingMiddleware，评分由独立子 Agent 完成——不是让运动员自己当裁判，还能调工具验证硬数据。"

---

## 动手实验

### 🟢 青铜：跑通 reflection_agent.py

1. 把第五节的完整代码存成 `reflection_agent.py`
2. 用 mock 数据（"王奶奶"那段录音）跑通
3. 观察输出：迭代了几轮？passed 是 true 吗？critique 说了什么？
4. 故意改录音（如把"36度8"改成"38度6"），观察 Critic 是否能抓到体温异常

```python
recording = "今天给王奶奶量了体温，38度6，血压高压145低压95，她说恶心不想吃饭。"
result = run_reflection(recording)
print(f"迭代 {result['iterations']} 轮，通过: {result['passed']}")
print(result["final_draft"])
```

### 🟡 白银：扩展 Critic 审查维度

1. 在 Critic 的 system_prompt 里加第四维度：**类型检查**（temperature 必须 float、blood_pressure 必须 int）
2. 加第五维度：**逻辑自洽**（is_abnormal=true 但无异常依据 → 判为过度告警）
3. 准备 5 段不同录音（正常/异常/有遗漏/有错位/过度告警），跑 Reflection 看每段迭代几轮
4. 整理表格：录音 → 发现的问题 → 修正后结果 → 迭代轮数

```python
test_recordings = [
    "今天给张爷爷量了体温，36度5，血压120/80，精神挺好，吃饭正常。",  # 正常
    "今天给李奶奶量了体温，39度2，血压160/100，她说头痛得很厉害。",      # 明显异常
    "今天给王爷爷量了体温，36度8，血压130/85。",                        # 信息不全
    "今天给赵奶奶量了体温，37度8，血压140/90，她说有点咳嗽，精神还行。",  # 边界异常
    "今天给孙爷爷量了体温，36度5，血压115/75，吃饭正常。精神不太好。",     # 精神欠佳
]
```

### 🔴 王者：用 RubricGradingMiddleware 重写并对比

1. 安装 deepagents：`pip install deepagents`
2. 用第七节 Middleware 方式重写 Reflection
3. 定义 rubric（5 条标准）+ 评分工具（check_vital_ranges）
4. 对比两种方式：同一批录音，StateGraph vs Middleware 哪个更准？更快？token 消耗少？
5. 写对比报告：两种方式在 准确率/迭代轮数/token 消耗/可调试性 上的差异

---

## 踩坑记录 🕳️

### 坑 1：Critic 和生成者同模型，容易"互相包庇"

同源模型思维模式相似，生成者犯的错 Critic 未必能发现，容易"放水"判 passed=true。

**解决：** Critic 用不同模型（生成用 gpt-4o-mini，Critic 用 claude-haiku-4-5），或至少用不同 system_prompt 强化角色差异。关键场景用更强模型当 Critic。

### 坑 2：没设 max_iterations，死循环烧 token

Critic 永远不满意（"还可以更好"），generation_node 无限循环，token 烧到天荒地老。

**解决：** 条件边硬限 `pass_count >= MAX_ITERATIONS`（设 3 轮），达到上限强制输出并标记"未通过完整审查，需人工复核"。养老场景宁可强制输出后人工复核，也不能让 Agent 卡死。

### 坑 3：Critic 输出的 JSON 解析失败

LLM 偶尔输出多余文本或 markdown 包裹，导致 `json.loads` 报错，passed 拿不到，循环中断。

**解决：** 用 LangChain 的 `with_structured_output` 强制 JSON（Week 03 学过）；或正则提取 `re.search(r'\{.*\}', text, re.DOTALL)`；解析失败时保守判 `passed=False` 再跑一轮。

### 坑 4：Critic 误判导致过度修改

Critic 反馈不一定全对，也可能把对的判成错的。generation_node 盲目服从 critique，可能"改对了 A 又改坏了 B"。

**解决：** generation_node 的 prompt 加"参考以下反馈修正，但以原文为准，反馈可能有误"；Critic prompt 加"只指出有把握的问题，不确定的不报"。

### 坑 5：Middleware 内部循环不可调试

RubricGradingMiddleware 把循环封装在内部，只看到最终输出，看不到中间哪轮 Grader 说了什么。

**解决：** 开发调试阶段用 StateGraph（每步可见）；生产用 Middleware 但开 verbose 日志；关键场景两者结合。

---

## 副线笔记

### Claude Code 内部有没有 Reflection 机制

Day 01-02 我们用 Claude Code 结对编程。反问：Claude Code 自己内部有没有 Reflection 机制？

**结论：有，而且是多层的。** 观察到的现象：

1. **改代码前先自检**：改完代码后会重新读一遍检查——这像 reflection_node 的自反思
2. **跑测试验证**：改完主动跑测试（如 `pytest`），用测试结果（硬数据）验证——对应 Grader 调工具获取硬证据
3. **报错后修正循环**：测试失败时读报错信息（相当于 critique），针对性修正，再跑测试——这就是"生成→审查→反馈→修正"循环

```
Claude Code 内部的 Reflection：改代码 → 自检+跑测试 → 通过则继续 / 失败则读报错 → 改代码 → 再跑测试
```

| 维度 | 我们的 reflection_agent | Claude Code 内部 |
|------|------------------------|-----------------|
| Critic 是谁 | 独立 LLM 调用 | 同一个 Claude（自反思） |
| 验证方式 | LLM 语义审查 | 跑测试（硬数据）+ 语义自检 |
| 循环终止 | max_iterations 或 Critic 判 passed | 测试通过或用户喊停 |

关键差异：**Claude Code 用"测试"这个硬数据验证，比纯 LLM 语义审查更可靠**。这印证了 RubricGradingMiddleware 的设计哲学——Grader 能调工具获取硬证据，胜过纯推理。

> **思考题：** 养老场景有没有"硬数据"可验证？提示：体温/血压范围校验可做成工具（check_vital_ranges），让 Critic 调用获取硬证据，而非纯靠 LLM 推理。这就是第七节王者实验的方向。

---

## 检查清单

- [ ] 理解 Reflection 本质：生成→Critic 审查→反馈→定向修正→循环到"够好"
- [ ] 能用 Code Review 类比讲清 Reflection 的价值（你写代码→Reviewer 查→退回改→通过才合并）
- [ ] 理解提取 Agent 三类错：字段填错、字段遗漏、异常没标记
- [ ] 知道 Pydantic 校验（格式层）和 Reflection（语义层）的区别
- [ ] 跑通了 reflection_agent.py，观察到 Critic 怎么反馈、Agent 怎么修正
- [ ] 理解 Critic 三维度审查：完整性、一致性、异常标记
- [ ] 知道 2026 官方推荐的 RubricGradingMiddleware 做法，能说清和 StateGraph 的差异
- [ ] 能回答面试 Q8：Code Review 类比 + 两种实现方式 + 踩过的坑
- [ ] 理解 Reflection 不是无脑重试，而是带着反馈的定向修正
- [ ] 知道 Claude Code 内部也有 Reflection（自检 + 跑测试验证）

---

## 下课预告

> **Day 04 — Agentic RAG 深度：冲突处理 + Reranking（面试 Q13, Q16）。** 今天我们让提取结果经过了 Critic 复审，质量有保障了。但养老系统还有个问题：历史记录会冲突——今天量体温 36.8，但昨天的记录里是 38.6，哪个对？明天学 Agentic RAG 的冲突处理：用元数据加权 + 多 Agent 辩论解决历史记录矛盾。还要学 Cross-Encoder Reranking（BGE-Reranker）提升检索准确度——Week 04 的基础 RAG 检索回来一堆没用的，Reranking 能把它重排出最相关的。这是 Week 04 基础 RAG 的深化升级，也是面试 Q13（检索冲突）和 Q16（提升准确度）的核心。
