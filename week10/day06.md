# Day 06 — 多 Agent 编排（Subagents 模式）

## 学习目标

Day 01 到 Day 05，我们像搭积木一样一块一块拼出了养老护工智能记录系统的零件：ASR 把语音转文本（Day 01）、提取 Agent 把文本变结构化表单（Day 02）、Reflection 让提取结果自纠错（Day 03）、Agentic RAG 解决历史记录冲突（Day 04）、趋势 Agent 对比历史发现变化（Day 05）。但这些都是各自跑的独立模块——护工录一段音，你得一节一节手动串起来调。今天我们用 Week 07 学的 Subagents 模式把它们编排成一个完整系统：一个 Supervisor（主编排器）接收护工录音，自动分派给五个子 Agent（提取/异常/趋势/建议/通知），像流水线一样把一段语音变成一条完整的护理记录 + 异常预警 + 通知消息。

这是本周的"组装日"。Week 07 我们讲了四大模式（Subagents / Handoffs / Skills / Router）和上下文工程，今天把那套理论真正落地到养老场景。多 Agent 编排是面试 Q9 的高频考点——"多个 Agent 怎么协作"。养老场景恰好是 Subagents 模式的完美主场：任务可拆分、子任务上下文要隔离、有明确的流水线顺序。

学完今天你能：

1. 理解为什么单 Agent 塞五个功能会"上下文爆炸"，以及多 Agent 编排如何通过上下文隔离解决它，能说清 Subagents 模式在养老场景为什么最合适
2. 设计五个子 Agent（提取/异常/趋势/建议/通知）的职责分工、输入输出契约，画出 Supervisor 的分派编排图
3. 用 LangGraph 的 `StateGraph` 搭 Supervisor 编排逻辑，配合 `create_agent` 创建五个子 Agent，实现"提取→并行(异常+趋势)→建议→通知"的流水线，并说清并行 fan-out 怎么做
4. 回答面试选型题：为什么选 LangGraph Subagents 而不是 CrewAI，能从控制流/可调试性/生态/学习曲线四个维度对比

---

## 一、为什么需要多 Agent 编排

### 1.1 单 Agent 的问题：五个功能塞一个上下文

前五天搭的模块，如果不做编排，最朴素的"合体"方式是把它们全塞进一个 Agent——给它提取的 prompt、异常阈值规则、历史检索工具、建议生成逻辑、通知发送工具，全部丢进一个 `create_agent`：

```python
# 反面教材：一个 Agent 扛五件事
do_everything_agent = create_agent(
    model=model,
    tools=[fetch_history, check_vitals, send_notification, get_care_guideline, ...],
    system_prompt=(
        "你是养老记录全能助手：先提取结构化记录，再检测异常，"
        "再对比历史趋势，再生成护理建议，最后发通知……"
    ),
    checkpointer=InMemorySaver(),
)
```

这看着省事，但 Week 07 Day 01 讲过单 Agent 的四大痛点，在这里全部应验：

| 痛点 | 在养老场景的表现 |
|------|----------------|
| 工具选择困惑 | 工具一多，Agent 在"该先 fetch_history 还是先 check_vitals"上犹豫，选错工具 |
| 上下文膨胀 | 提取的原始录音、历史检索返回的一堆记录、异常阈值规则全堆在一个 messages 里，到第四步模型已经"忘了"第一步提取的体温是多少 |
| 领域太杂推理混乱 | "提取文本"和"判断血压异常"是两种思维模式，混在一起模型推理质量下降 |
| 无法并行 | 异常检测和趋势分析互不依赖，却只能串行跑，白白浪费时间 |

> **前端类比：** 这就像把一个后台管理系统的所有页面（用户管理/订单/统计/权限/设置）全塞进一个巨石组件，state 混成一锅粥，改一处怕动全身。单 Agent 扛五件事就是后端版的"巨石组件"。

### 1.2 多 Agent 的优势：上下文隔离

多 Agent 编排的核心价值不是"Agent 变多了"，而是**上下文隔离**——每个子 Agent 只管一件事，它的上下文里只有这件事需要的信息，别家的事不进来串味。

```
单 Agent（巨石）：   ASR文本 + 历史记录 + 异常规则 + 建议模板 + 通知逻辑  → 全堆一个上下文
多 Agent（编排）：   提取Agent只看ASR文本 / 异常Agent只看CareRecord+阈值 / 趋势Agent只看记录+历史
                     → 各管各的，互不干扰，主Agent只收结论
```

在养老场景，隔离的价值特别明显：异常检测 Agent 只需要 CareRecord + 阈值规则，不需要知道原始录音长什么样；趋势 Agent 只需要 CareRecord + 历史记录，不需要异常阈值规则。上下文短了，每个子 Agent 的推理反而更准、更省 token。

> **前端类比：** 多 Agent 就像**微前端**——每个子应用（子 Agent）独立运行、独立上下文、独立部署，主应用（Supervisor）只负责编排路由和传递数据。子应用之间不共享 store，靠事件/消息通信。微前端解决"巨石前端"的思路，和多 Agent 解决"巨石 Agent"的思路完全一致。

### 1.3 回顾 Week 07 四大模式

Week 07 Day 01 讲过 2026 年 LangChain 官方推荐的四大模式，先快速复习，看养老场景该选哪个：

| 模式 | 核心机制 | 适用场景 | 养老场景契合度 |
|------|---------|---------|---------------|
| **Subagents** | 主 Agent 把子 Agent 包装成 tool 调用，子 Agent 独立上下文，主 Agent 只收结论 | 任务可拆分、子任务上下文要隔离、有明确流水线 | ★★★★★ 完美契合 |
| **Handoffs** | 控制权在 Agent 间流转，共享同一份对话历史 | 多轮对话、角色会切换（客服流转） | ★★ 会把历史越积越长 |
| **Skills** | 按需加载知识/工具，单个 Agent 动态扩展能力 | 知识库庞大要按需加载 | ★★ 偏向"单 Agent 加技能" |
| **Router** | 分类后分发到对应 Agent，各管一类问题 | 意图分类后路由（客服分流） | ★★ 适合"二选一"分流而非流水线 |

养老场景的特点是：**任务是一条固定的流水线**（提取→异常→趋势→建议→通知），每一步的输入是上一步的输出，子任务之间上下文要隔离。这正是 Subagents 模式的主场——Handoffs 会让对话历史越积越长，Router 适合分流而非流水线，Skills 偏向单 Agent 扩展。

### 1.4 为什么用 Supervisor（StateGraph）当编排器

Subagents 模式里"主 Agent"有两种实现方式：

- **动态 Supervisor**：主 Agent 也是一个 LLM Agent，靠推理决定"现在该调哪个子 Agent"。灵活，但不确定性高，养老这种固定流水线没必要。
- **静态 Supervisor（StateGraph）**：用 LangGraph 的 StateGraph 把编排逻辑写成节点和边，确定性地按流水线分派。可预测、可调试、不烧 token。

养老记录是**固定流水线**——护工录完音，永远是"提取→异常→趋势→建议→通知"这五步，不需要 LLM 来决定顺序。所以 Supervisor 用 StateGraph 实现，节点和边把流程写死，确定性最高。这也是今天主代码的选择。

> **选型一句话：** 流程固定用 StateGraph（静态 Supervisor），流程要 LLM 临场决策才用动态 Supervisor。养老场景是前者，所以选 StateGraph。

---

## 二、五个子 Agent 设计

把 Day 01-05 的模块抽象成五个子 Agent，每个有明确的职责、输入、输出契约。契约清晰是多 Agent 协作的基础——Week 07 Day 06 讲过，子 Agent 之间靠"结构化结论"通信，不靠原始 messages 堆叠。

| 子 Agent | 职责 | 输入 | 输出 | 对应已学模块 |
|---------|------|------|------|-------------|
| **提取 Agent** | ASR 文本 → 结构化 CareRecord | ASR 文本 | CareRecord（JSON：姓名/体温/血压/症状/精神/异常标记） | Day 02 extraction_agent |
| **异常 Agent** | 检测生命体征异常 | CareRecord | 异常标记列表（哪些指标超标 + 等级） | Day 02 异常标记 + Day 03 阈值规则 |
| **趋势 Agent** | 对比历史记录发现变化 | CareRecord + 历史数据 | 趋势分析报告（体温/血压/情绪的变化趋势） | Day 05 trend_agent + Day 04 RAG |
| **建议 Agent** | 综合异常 + 趋势生成护理建议 | 异常列表 + 趋势报告 | 建议列表（饮食/用药/观察/就医建议） | Day 02 建议 + 业务规则 |
| **通知 Agent** | 根据建议 + 异常等级发通知 | 建议列表 + 异常等级 | 通知消息（给护工/家属/医生的差异化文案） | Day 07 通知分发预告 |

### 2.1 上下文隔离设计

每个子 Agent 只看到它完成任务所需的信息，不多不少（Week 07 Day 06 的最小化 + 隔离原则）：

```
提取 Agent 的上下文：  只看 ASR 文本 + 提取 prompt          ← 不看历史、不看阈值
异常 Agent 的上下文：  只看 CareRecord + 阈值规则工具       ← 不看原始录音、不看历史
趋势 Agent 的上下文：  只看 CareRecord + fetch_history 工具  ← 不看异常阈值、不看建议模板
建议 Agent 的上下文：  只看 异常列表 + 趋势报告              ← 不看原始录音、不看阈值细节
通知 Agent 的上下文：  只看 建议列表 + 异常等级              ← 不看趋势细节、不看提取过程
```

注意异常和趋势**互不依赖**——它们都只依赖提取出来的 CareRecord，所以可以**并行**跑。这是后面 fan-out 并行的依据。

### 2.2 数据流契约

子 Agent 之间用 JSON 字符串传递结构化结论（和 Day 02/03 一致，draft 都是 JSON 文本）。Supervisor 的 State 负责承载这些中间产物：

```
asr_text ──extract──▶ care_record(JSON)
                          │
              ┌───────────┴───────────┐
              ▼                       ▼
        anomalies(JSON)         trend_report(文本)
              └───────────┬───────────┘
                          ▼
                    advice_list(JSON)
                          │
                          ▼
                    notification(文本)
```

每个箭头就是一次"子 Agent 返回结论 → 写入 State → 下一个子 Agent 读取"。原始的 messages 推理过程全部留在子 Agent 自己的 checkpointer 里，不进 Supervisor 的 State——这就是上下文隔离。

---

## 三、Supervisor 编排逻辑

### 3.1 编排五步走

Supervisor（StateGraph）接收 ASR 文本后，按固定流水线分派：

1. **接收** — Supervisor 接收 ASR 文本，写入 State
2. **分派提取** — 调用提取 Agent → 得到 CareRecord
3. **并行分派异常 + 趋势** — CareRecord 同时喂给异常 Agent 和趋势 Agent（fan-out 并行）
4. **汇总给建议** — 异常列表 + 趋势报告汇合后（barrier）给建议 Agent
5. **最后给通知** — 建议 + 异常等级给通知 Agent → 输出

### 3.2 ASCII 架构图

```
                    护工 ASR 文本
                         │
                         ▼
              ┌────────────────────────┐
              │   Supervisor          │
              │  (LangGraph StateGraph) │
              └────────────────────────┘
                         │
                  ① 分派给提取
                         ▼
              ┌────────────────────────┐
              │  提取 Agent            │
              │  ASR文本 → CareRecord  │
              └────────────────────────┘
                         │
            ② 并行分派（fan-out）
            ┌────────────┴────────────┐
            ▼                         ▼
   ┌──────────────────┐      ┌──────────────────┐
   │  异常 Agent       │      │  趋势 Agent       │
   │  生命体征异常检测  │      │  对比历史记录趋势  │
   └──────────────────┘      └──────────────────┘
            └────────────┬────────────┘
                ③ 汇总（barrier 自动等待）
                         ▼
              ┌────────────────────────┐
              │  建议 Agent            │
              │  异常+趋势 → 护理建议   │
              └────────────────────────┘
                         │
                         ▼
              ┌────────────────────────┐
              │  通知 Agent            │
              │  建议+等级 → 通知消息   │
              └────────────────────────┘
                         │
                         ▼
                   输出完整记录
```

### 3.3 用 LangGraph StateGraph 实现编排

LangGraph 的 StateGraph 用"节点 + 边"描述流程。节点是执行单元（调子 Agent），边是数据流向。关键技巧：

- **并行（fan-out）**：从一个节点引出两条边到两个节点，它们会在同一个 superstep 并行执行。
- **汇合（barrier）**：两个并行节点的边都指向同一个节点，该节点会自动等两个上游都完成才执行——这就是步骤③的"汇总"。

```
START → extract → anomaly ─┐
                 → trend ───┴→ advice → notify → END
```

对应代码骨架（完整代码见第四节）：

```python
graph = StateGraph(OrchestratorState)
graph.add_node("extract", extract_node)      # 提取
graph.add_node("anomaly", anomaly_node)      # 异常
graph.add_node("trend", trend_node)          # 趋势
graph.add_node("advice", advice_node)        # 建议
graph.add_node("notify", notify_node)        # 通知

graph.add_edge(START, "extract")
# ② fan-out：extract 同时指向 anomaly 和 trend，并行执行
graph.add_edge("extract", "anomaly")
graph.add_edge("extract", "trend")
# ③ barrier：anomaly 和 trend 都指向 advice，advice 等两者都完成
graph.add_edge("anomaly", "advice")
graph.add_edge("trend", "advice")
graph.add_edge("advice", "notify")
graph.add_edge("notify", END)
```

注意 State 里并行的两个节点都要写的字段，必须用 `Annotated[list, operator.add]` 做 reducer，否则并行写入会冲突。提取只写 `care_record`、异常只写 `anomalies`、趋势只写 `trend_report`，互不冲突；只有"执行轨迹"这种两者都追加的字段才需要 add reducer。

---

## 四、完整 orchestrator.py

下面是完整的多 Agent 编排系统。每个子 Agent 用 `create_agent` 创建（带独立 checkpointer 做上下文隔离），Supervisor 用 `StateGraph` 编排。工具用 mock 实现，所以代码无需真实外部服务即可跑通。

```python
"""orchestrator.py — 多 Agent 编排（Subagents 模式）

养老护工智能记录系统 Day 06 产出
用 LangGraph StateGraph 当 Supervisor，编排五个 create_agent 子 Agent：
  提取 → [异常 ‖ 趋势] → 建议 → 通知

设计要点：
1. 每个子 Agent 用 create_agent 创建，带独立 InMemorySaver，上下文隔离
2. Supervisor 用 StateGraph 的节点和边编排，确定性流水线
3. 异常和趋势互不依赖，fan-out 并行，advice 节点 barrier 自动汇合
4. 工具用 mock 实现，无需真实 ASR/数据库/通知服务即可跑通

依赖（2026 版本）：pip install langchain langgraph
"""

from langchain.agents import create_agent
from langchain.tools import tool
from langchain.chat_models import init_chat_model
from langgraph.graph import StateGraph, END, START
from langgraph.checkpoint.memory import InMemorySaver
from langchain_core.messages import HumanMessage
from typing import TypedDict, Annotated
from pydantic import BaseModel, Field, ValidationError
import operator
import json
import textwrap
import time
import re


# ============================================================
# 零、全局配置：阈值/模型/重试，集中管理便于调参（对应 Day 03 的规则）
# ============================================================
VITAL_THRESHOLDS = {
    "temperature": {"warning": 37.3, "critical": 38.5},   # 体温阈值
    "systolic": {"warning": 140, "critical": 160},         # 收缩压阈值
    "diastolic": {"warning": 90, "critical": 105},          # 舒张压阈值
    "heart_rate_low": 50,                                   # 心率下限
    "heart_rate_high": 100,                                 # 心率上限
}

MODEL_NAME = "openai:gpt-4o-mini"   # 子 Agent 模型，可用便宜模型
MAX_RETRIES = 2                      # 子 Agent 调用失败重试次数（JSON 解析失败时）
ENABLE_DEBUG_LOG = True              # 调试日志开关，生产关掉


def debug_log(msg: str) -> None:
    """统一调试日志入口，方便一键开关，对应 Week 07 Day 06 的上下文检查插桩。"""
    if ENABLE_DEBUG_LOG:
        print(f"  [debug] {msg}")


def safe_json_load(text: str) -> dict | None:
    """容错解析 LLM 输出的 JSON。
    LLM 偶尔用三反引号代码块（如 json 包裹）或带多余文本，先正则提取再解析。
    解析失败返回 None（调用方据此决定重试或降级）。"""
    if not text:
        return None
    # 去掉 markdown 代码块包裹
    cleaned = re.search(r"\{.*\}", text, re.DOTALL)
    candidate = cleaned.group(0) if cleaned else text
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return None


def invoke_with_retry(agent, content: str, thread_id: str) -> str:
    """带重试的子 Agent 调用：失败（空输出/异常）时重试，超 MAX_RETRIES 抛错。
    养老场景宁可重试几次，也不能让一个子 Agent 偶发失败拖垮整条流水线。"""
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            debug_log(f"调用子 Agent（第 {attempt}/{MAX_RETRIES} 次），thread={thread_id}")
            result = agent.invoke(
                {"messages": [HumanMessage(content=content)]},
                config={"configurable": {"thread_id": thread_id}},
            )
            output = result["messages"][-1].content
            if output and output.strip():
                return output
            debug_log("子 Agent 返回空内容，重试...")
        except Exception as err:  # noqa: BLE001  调用方会决定是否降级
            last_err = err
            debug_log(f"子 Agent 调用异常：{err}，重试...")
    raise RuntimeError(f"子 Agent {thread_id} 重试 {MAX_RETRIES} 次仍失败：{last_err}")


# ============================================================
# 一、Supervisor 的状态机：承载子 Agent 之间的中间产物
# ============================================================
class OrchestratorState(TypedDict):
    """编排状态：每个 key 是一个子 Agent 的输出（结构化结论）。
    原始 messages 推理过程留在子 Agent 自己的 checkpointer，不进这里。"""
    asr_text: str                                   # 输入：ASR 转写文本（全程不变）
    care_record: str                                 # 提取 Agent 输出：CareRecord JSON
    anomalies: str                                   # 异常 Agent 输出：异常标记列表 JSON
    trend_report: str                                # 趋势 Agent 输出：趋势分析报告
    advice_list: str                                  # 建议 Agent 输出：建议列表 JSON
    notification: str                                # 通知 Agent 输出：通知消息
    severity: str                                     # 异常等级（normal/warning/critical）
    steps: Annotated[list[str], operator.add]         # 执行轨迹（异常+趋势并行追加，需 add reducer）


# ============================================================
# 二、数据模型：CareRecord（提取的目标结构，和 Day 02 一致）
# ============================================================
class CareRecord(BaseModel):
    """结构化护理记录，提取 Agent 的目标输出。"""
    patient_name: str = Field(..., description="老人姓名")
    temperature: float | None = Field(None, description="体温（℃）")
    blood_pressure_systolic: int | None = Field(None, description="收缩压")
    blood_pressure_diastolic: int | None = Field(None, description="舒张压")
    heart_rate: int | None = Field(None, description="心率")
    diet: str = Field("", description="饮食情况")
    mental_status: str = Field("", description="精神状态")
    symptoms: list[str] = Field(default_factory=list, description="症状列表")
    is_abnormal: bool = Field(False, description="是否有异常")


class AnomalyReport(BaseModel):
    """异常 Agent 的结构化输出，用于下游解析校验。"""
    abnormal_items: list[str] = Field(default_factory=list, description="异常项列表")
    severity: str = Field("normal", description="异常等级 normal/warning/critical")
    summary: str = Field("", description="一句话异常概况")


class AdviceReport(BaseModel):
    """建议 Agent 的结构化输出。"""
    suggestions: list[str] = Field(default_factory=list, description="护理建议列表")
    priority: str = Field("low", description="优先级 high/medium/low")
    reason: str = Field("", description="建议依据")


def parse_model(text: str, model_cls: type[BaseModel]) -> BaseModel | None:
    """把 LLM 文本输出解析成指定 Pydantic 模型，解析失败返回 None。
    对应坑 3：子 Agent 输出 JSON 解析失败时的容错。"""
    data = safe_json_load(text)
    if data is None:
        debug_log(f"解析 {model_cls.__name__} 失败：JSON 无法解析")
        return None
    try:
        return model_cls.model_validate(data)
    except ValidationError as err:
        debug_log(f"解析 {model_cls.__name__} 字段校验失败：{err}")
        return None


# ============================================================
# 三、子 Agent 可调用的工具（@tool，mock 实现）
# 工具让子 Agent 真正跑 ReAct 循环，而不只是纯文本推理
# ============================================================

# ---- 提取 Agent 的工具 ----
@tool
def lookup_patient(name: str) -> str:
    """根据老人姓名查询老人档案（年龄、既往病史等）。
    name 为老人姓名。用于提取时补充背景信息。"""
    # mock：实际应查数据库
    mock_db = {
        "王奶奶": "82岁，高血压病史，长期服用降压药",
        "李爷爷": "78岁，糖尿病，胰岛素治疗",
        "张奶奶": "75岁，冠心病，日常活动受限",
    }
    return mock_db.get(name, f"{name}：暂无档案，请护工补充")


# ---- 异常 Agent 的工具 ----
@tool
def check_vital_thresholds(temperature: float, systolic: int, diastolic: int,
                           heart_rate: int) -> str:
    """检查生命体征是否超出阈值。返回超标的指标和等级。
    temperature 体温，systolic 收缩压，diastolic 舒张压，heart_rate 心率。"""
    issues = []
    t_cfg = VITAL_THRESHOLDS["temperature"]
    if temperature and temperature > t_cfg["critical"]:
        issues.append(f"体温 {temperature}℃ 高热（>{t_cfg['critical']}），等级 critical")
    elif temperature and temperature > t_cfg["warning"]:
        issues.append(f"体温 {temperature}℃ 偏高（>{t_cfg['warning']}），等级 warning")
    s_cfg = VITAL_THRESHOLDS["systolic"]
    if systolic and systolic > s_cfg["critical"]:
        issues.append(f"收缩压 {systolic} 严重偏高（>{s_cfg['critical']}），等级 critical")
    elif systolic and systolic > s_cfg["warning"]:
        issues.append(f"收缩压 {systolic} 偏高（>{s_cfg['warning']}），等级 warning")
    d_cfg = VITAL_THRESHOLDS["diastolic"]
    if diastolic and diastolic > d_cfg["warning"]:
        issues.append(f"舒张压 {diastolic} 偏高（>{d_cfg['warning']}），等级 warning")
    hr_low = VITAL_THRESHOLDS["heart_rate_low"]
    hr_high = VITAL_THRESHOLDS["heart_rate_high"]
    if heart_rate and (heart_rate > hr_high or heart_rate < hr_low):
        issues.append(f"心率 {heart_rate} 异常（正常 {hr_low}-{hr_high}），等级 warning")
    return "; ".join(issues) if issues else "生命体征均在正常范围"


# ---- 趋势 Agent 的工具 ----
@tool
def fetch_history_records(patient_name: str, days: int = 7) -> str:
    """查询老人最近 N 天的历史护理记录。patient_name 为老人姓名，days 为天数。
    返回历史记录摘要，用于趋势对比。"""
    # mock：实际应查 Week 05 的向量库 + Day 04 的 Agentic RAG
    mock_history = {
        "王奶奶": (
            "近7天记录：\n"
            "- 体温趋势：36.5→36.8→37.1→37.8（持续上升，3天上升1.3℃）\n"
            "- 血压趋势：130/80→138/85→145/92→150/95（收缩压持续升高）\n"
            "- 精神状态：前5天活跃，近2天明显倦怠\n"
            "- 饮食：食量从正常递减到半碗"
        ),
        "李爷爷": (
            "近7天记录：\n"
            "- 血糖波动大：空腹 6.5→7.8→9.2（连续3天超标）\n"
            "- 精神状态平稳，饮食正常"
        ),
    }
    return mock_history.get(patient_name, f"{patient_name}：近{days}天无历史记录")


# ---- 建议 Agent 的工具 ----
@tool
def get_care_guideline(symptom: str) -> str:
    """根据症状查询护理指南。symptom 为症状描述（如"发热""血压高"）。
    返回该症状的标准护理建议。"""
    # mock：实际应查护理知识库
    guidelines = {
        "发热": "物理降温，多饮水，每4小时复测体温；>38.5℃ 通知医生",
        "血压高": "低盐饮食，按时服药，每日早晚测血压；>160 警惕高血压危象",
        "头晕": "防跌倒，卧床休息，监测血压变化；持续不缓解就医",
        "食欲下降": "少食多餐，清淡易消化，记录每日进食量",
    }
    for key, val in guidelines.items():
        if key in symptom:
            return val
    return f"未找到'{symptom}'的专项指南，建议观察并咨询医生"


# ---- 通知 Agent 的工具 ----
@tool
def send_notification(recipient: str, message: str, channel: str = "wechat") -> str:
    """发送通知消息给指定接收人。recipient 为接收人（护工/家属/医生），
    message 为通知内容，channel 为渠道（wechat/sms/phone）。"""
    # mock：实际应接微信/短信网关
    return f"[{channel}] 已通知 {recipient}：{message[:50]}..."


# ============================================================
# 四、子 Agent 工厂：每个用 create_agent 创建，独立 checkpointer
# ============================================================


def build_extraction_agent():
    """提取 Agent：ASR 文本 → CareRecord JSON。对应 Day 02。"""
    prompt = textwrap.dedent("""\
        你是养老护理记录提取助手。根据护工录音文本，提取结构化护理记录，输出 JSON。
        字段：patient_name, temperature(float), blood_pressure_systolic(int),
        blood_pressure_diastolic(int), heart_rate(int), diet, mental_status,
        symptoms(列表), is_abnormal(布尔)。
        体温>37.3 或有症状 或 精神欠佳 时 is_abnormal 为 true。
        可调用 lookup_patient 补充老人背景。只输出 JSON，不要多余解释。""")
    return create_agent(
        model=init_chat_model(MODEL_NAME, temperature=0),
        tools=[lookup_patient],
        system_prompt=prompt,
        checkpointer=InMemorySaver(),  # 独立实例，上下文隔离
    )


def build_anomaly_agent():
    """异常 Agent：检测生命体征异常。"""
    prompt = textwrap.dedent("""\
        你是生命体征异常检测助手。读取护理记录 JSON，调用 check_vital_thresholds
        检查体温/血压/心率是否超标，再结合 symptoms 判断是否还有其他异常。
        输出 JSON：{"abnormal_items": ["指标1：值（等级）"], "severity": "normal/warning/critical",
        "summary": "一句话异常概况"}。
        多个 critical 或 任一 critical 都算 critical 级；只有 warning 算 warning；无异常算 normal。""")
    return create_agent(
        model=init_chat_model(MODEL_NAME, temperature=0),
        tools=[check_vital_thresholds],
        system_prompt=prompt,
        checkpointer=InMemorySaver(),
    )


def build_trend_agent():
    """趋势 Agent：对比历史记录发现变化。对应 Day 05。"""
    prompt = textwrap.dedent("""\
        你是护理趋势分析助手。读取当前护理记录，调用 fetch_history_records
        查询历史，对比当前值和历史趋势，找出变化方向（上升/下降/平稳）。
        输出文本报告：分 生命体征趋势、精神状态趋势、饮食趋势 三段，
        每段说明变化方向和幅度，最后给出"是否需要关注"的结论。""")
    return create_agent(
        model=init_chat_model(MODEL_NAME, temperature=0),
        tools=[fetch_history_records],
        system_prompt=prompt,
        checkpointer=InMemorySaver(),
    )


def build_advice_agent():
    """建议 Agent：综合异常+趋势生成护理建议。"""
    prompt = textwrap.dedent("""\
        你是护理建议助手。综合异常检测结果和趋势分析报告，生成针对性护理建议。
        可针对每个症状调用 get_care_guideline 查询标准护理指南。
        输出 JSON：{"suggestions": ["建议1", "建议2", ...], "priority": "high/medium/low",
        "reason": "为什么这些建议"}。
        建议要具体可执行（如"今日每4小时复测体温"），不要空话。""")
    return create_agent(
        model=init_chat_model(MODEL_NAME, temperature=0),
        tools=[get_care_guideline],
        system_prompt=prompt,
        checkpointer=InMemorySaver(),
    )


def build_notification_agent():
    """通知 Agent：根据建议+等级生成差异化通知。对应 Day 07 预告。"""
    prompt = textwrap.dedent("""\
        你是通知分发助手。根据护理建议和异常等级，生成通知消息并调用 send_notification 发送。
        通知对象按等级区分：
        - normal：仅通知责任护工（日常记录）
        - warning：通知护工 + 家属（需关注）
        - critical：通知护工 + 家属 + 医生（需立即处理）
        输出最终的通知消息汇总文本，包含发给谁、什么内容、什么渠道。""")
    return create_agent(
        model=init_chat_model(MODEL_NAME, temperature=0),
        tools=[send_notification],
        system_prompt=prompt,
        checkpointer=InMemorySaver(),
    )


# ============================================================
# 五、Supervisor 的节点函数：每个节点调一个子 Agent，写结论进 State
# ============================================================

def extract_node(state: OrchestratorState) -> dict:
    """节点①：调提取 Agent，ASR 文本 → CareRecord。"""
    print("\n[Supervisor] ① 分派给 提取 Agent ...")
    agent = build_extraction_agent()
    content = f"护工录音：\n{state['asr_text']}\n\n请提取结构化护理记录 JSON。"
    care_record = invoke_with_retry(agent, content, thread_id="extract")
    # 尝试解析校验，校验失败不阻塞流水线，只记日志
    parsed = parse_model(care_record, CareRecord)
    if parsed:
        debug_log(f"CareRecord 校验通过：{parsed.patient_name}, 体温={parsed.temperature}")
    print(f"[提取 Agent] 输出 CareRecord（前80字）：{care_record[:80]}...")
    return {
        "care_record": care_record,
        "steps": ["① extract: ASR文本 → CareRecord"],
    }


def anomaly_node(state: OrchestratorState) -> dict:
    """节点②A：调异常 Agent，检测生命体征异常（与趋势并行）。"""
    print("\n[Supervisor] ②A 分派给 异常 Agent ...")
    agent = build_anomaly_agent()
    content = f"护理记录 JSON：\n{state['care_record']}\n\n请检测异常，输出 JSON。"
    anomalies = invoke_with_retry(agent, content, thread_id="anomaly")
    # 用结构化模型解析 severity，解析失败降级为 normal
    report = parse_model(anomalies, AnomalyReport)
    severity = report.severity if report else "normal"
    print(f"[异常 Agent] severity={severity}，异常项已生成")
    return {
        "anomalies": anomalies,
        "severity": severity,
        "steps": [f"②A anomaly: 异常检测 severity={severity}"],
    }


def trend_node(state: OrchestratorState) -> dict:
    """节点②B：调趋势 Agent，对比历史记录（与异常并行）。"""
    print("\n[Supervisor] ②B 分派给 趋势 Agent ...")
    agent = build_trend_agent()
    content = (f"当前护理记录 JSON：\n{state['care_record']}\n\n"
               f"请查询历史并对比趋势，输出趋势报告。")
    trend_report = invoke_with_retry(agent, content, thread_id="trend")
    print(f"[趋势 Agent] 趋势报告已生成（前80字）：{trend_report[:80]}...")
    return {
        "trend_report": trend_report,
        "steps": ["②B trend: 历史趋势对比"],
    }


def advice_node(state: OrchestratorState) -> dict:
    """节点③：调建议 Agent，综合异常+趋势生成建议（barrier 自动等待②A②B）。"""
    print("\n[Supervisor] ③ 汇总后分派给 建议 Agent ...")
    agent = build_advice_agent()
    content = (
        f"异常检测结果：\n{state['anomalies']}\n\n"
        f"趋势分析报告：\n{state['trend_report']}\n\n"
        f"请综合两者生成护理建议，输出 JSON。"
    )
    advice_list = invoke_with_retry(agent, content, thread_id="advice")
    report = parse_model(advice_list, AdviceReport)
    if report:
        debug_log(f"建议优先级={report.priority}，共 {len(report.suggestions)} 条")
    print(f"[建议 Agent] 建议列表已生成（前80字）：{advice_list[:80]}...")
    return {
        "advice_list": advice_list,
        "steps": ["③ advice: 异常+趋势 → 护理建议"],
    }


def notify_node(state: OrchestratorState) -> dict:
    """节点④：调通知 Agent，根据建议+等级发通知。"""
    print("\n[Supervisor] ④ 分派给 通知 Agent ...")
    agent = build_notification_agent()
    content = (
        f"护理建议：\n{state['advice_list']}\n\n"
        f"异常等级：{state['severity']}\n\n"
        f"请根据等级生成并发送通知，输出通知汇总。"
    )
    notification = invoke_with_retry(agent, content, thread_id="notify")
    print(f"[通知 Agent] 通知已发送（前80字）：{notification[:80]}...")
    return {
        "notification": notification,
        "steps": ["④ notify: 建议+等级 → 通知分发"],
    }


# ============================================================
# 六、组装 Supervisor：StateGraph 节点 + 边 = 编排逻辑
# ============================================================
def build_orchestrator_graph():
    """组装 Supervisor 的 StateGraph。
    流程：START → extract → [anomaly ‖ trend] → advice → notify → END
    其中 [anomaly ‖ trend] 是 fan-out 并行，advice 是 barrier 汇合。"""
    graph = StateGraph(OrchestratorState)

    # 注册五个节点（每个节点调一个子 Agent）
    graph.add_node("extract", extract_node)
    graph.add_node("anomaly", anomaly_node)
    graph.add_node("trend", trend_node)
    graph.add_node("advice", advice_node)
    graph.add_node("notify", notify_node)

    # 编排边：确定性的流水线
    graph.add_edge(START, "extract")
    # ② fan-out：extract 同时指向 anomaly 和 trend，并行执行
    graph.add_edge("extract", "anomaly")
    graph.add_edge("extract", "trend")
    # ③ barrier：anomaly 和 trend 都指向 advice，advice 等两者都完成
    graph.add_edge("anomaly", "advice")
    graph.add_edge("trend", "advice")
    # ④ 串行收尾
    graph.add_edge("advice", "notify")
    graph.add_edge("notify", END)

    checkpointer = InMemorySaver()
    return graph.compile(checkpointer=checkpointer)


# ============================================================
# 七、运行入口：把一段护工录音跑成完整记录
# ============================================================
def run_pipeline(asr_text: str) -> dict:
    """运行完整编排流水线，返回各阶段产物。
    输入：asr_text 护工录音的 ASR 转写文本
    输出：dict 含 care_record/anomalies/trend_report/advice_list/notification/severity/steps"""
    app = build_orchestrator_graph()
    initial_state: OrchestratorState = {
        "asr_text": asr_text,
        "care_record": "",
        "anomalies": "",
        "trend_report": "",
        "advice_list": "",
        "notification": "",
        "severity": "normal",
        "steps": [],
    }
    config = {"configurable": {"thread_id": "care-pipeline-001"}}
    final_state = app.invoke(initial_state, config=config)
    return {
        "care_record": final_state["care_record"],
        "anomalies": final_state["anomalies"],
        "trend_report": final_state["trend_report"],
        "advice_list": final_state["advice_list"],
        "notification": final_state["notification"],
        "severity": final_state["severity"],
        "steps": final_state["steps"],
    }


def print_result(result: dict) -> None:
    """美化打印编排结果。"""
    print("\n" + "=" * 60)
    print("多 Agent 编排结果")
    print("=" * 60)
    print(f"\n【执行轨迹】")
    for step in result["steps"]:
        print(f"  {step}")
    print(f"\n【异常等级】{result['severity']}")
    print(f"\n【CareRecord】\n{result['care_record']}")
    print(f"\n【异常检测】\n{result['anomalies']}")
    print(f"\n【趋势报告】\n{result['trend_report']}")
    print(f"\n【护理建议】\n{result['advice_list']}")
    print(f"\n【通知消息】\n{result['notification']}")
    print("\n" + "=" * 60)


# ============================================================
# 八、彩蛋：动态 Supervisor（LLM Agent 当编排器，对比静态 StateGraph）
# 流程不固定、要 LLM 临场决策时才用；养老场景是固定流水线，主代码用静态版
# ============================================================
def build_dynamic_supervisor():
    """动态 Supervisor：主 Agent 也是 create_agent，五个子 Agent 包装成它的 tool，
    由 LLM 决定调用顺序。灵活但不确定性高，固定流水线不推荐。"""
    # 把五个子 Agent 包成 tool，主 Agent 按需调用
    extract_agent = build_extraction_agent()
    anomaly_agent = build_anomaly_agent()
    trend_agent = build_trend_agent()
    advice_agent = build_advice_agent()
    notify_agent = build_notification_agent()

    @tool
    def call_extract(asr_text: str) -> str:
        """提取结构化护理记录。asr_text 为护工录音文本。流程第一步必调。"""
        return invoke_with_retry(
            extract_agent, f"护工录音：\n{asr_text}\n\n请提取 JSON。", "extract-dyn"
        )

    @tool
    def call_anomaly(care_record_json: str) -> str:
        """检测生命体征异常。care_record_json 为提取出的护理记录 JSON。"""
        return invoke_with_retry(
            anomaly_agent, f"护理记录 JSON：\n{care_record_json}\n\n请检测异常。", "anomaly-dyn"
        )

    @tool
    def call_trend(care_record_json: str) -> str:
        """对比历史趋势。care_record_json 为护理记录 JSON。可与异常并行。"""
        return invoke_with_retry(
            trend_agent, f"护理记录 JSON：\n{care_record_json}\n\n请对比趋势。", "trend-dyn"
        )

    @tool
    def call_advice(anomaly_result: str, trend_result: str) -> str:
        """综合异常和趋势生成建议。anomaly_result 为异常结果，trend_result 为趋势报告。"""
        content = f"异常：\n{anomaly_result}\n\n趋势：\n{trend_result}\n\n请生成建议 JSON。"
        return invoke_with_retry(advice_agent, content, "advice-dyn")

    @tool
    def call_notify(advice_result: str, severity: str) -> str:
        """发通知。advice_result 为建议，severity 为异常等级 normal/warning/critical。"""
        content = f"建议：\n{advice_result}\n\n等级：{severity}\n\n请发通知。"
        return invoke_with_retry(notify_agent, content, "notify-dyn")

    return create_agent(
        model=init_chat_model(MODEL_NAME, temperature=0),
        tools=[call_extract, call_anomaly, call_trend, call_advice, call_notify],
        system_prompt=(
            "你是养老记录编排主 Agent。流程：先 call_extract 提取记录，"
            "再 call_anomaly 和 call_trend（可并行），再 call_advice 综合建议，"
            "最后 call_notify 发通知。严格按此顺序。"
        ),
        checkpointer=InMemorySaver(),
    )


def print_summary(results: list[tuple[str, dict, float]]) -> None:
    """打印多场景结果汇总表（录音摘要/异常等级/耗时）。"""
    print("\n" + "=" * 60)
    print("多场景汇总")
    print("=" * 60)
    print(f"{'场景':<6}{'异常等级':<12}{'耗时(s)':<10}{'通知摘要'}")
    print("-" * 60)
    for name, result, elapsed in results:
        notif = result["notification"][:24].replace("\n", " ")
        print(f"{name:<6}{result['severity']:<12}{elapsed:<10.2f}{notif}...")
    print("=" * 60)


# ============================================================
# 九、主入口：三段测试录音，覆盖 正常/警告/危急 三种场景
# ============================================================
if __name__ == "__main__":
    test_recordings = [
        # 场景1：基本正常，轻度关注
        ("正常", "今天给王奶奶量了体温，36度8，血压高压135低压85，心率78。"
         "早饭喝了半碗粥，精神还行，就是有点咳嗽。"),
        # 场景2：明显异常，需关注（warning）
        ("警告", "今天给王奶奶量了体温，37度8，血压高压150低压95，心率88。"
         "她说今天有点头晕，早饭只吃了几口，精神不太好。"),
        # 场景3：危急，需立即处理（critical）
        ("危急", "今天给王奶奶量了体温，39度1，血压高压170低压105，心率110。"
         "她说头痛得厉害，恶心想吐，一整天没怎么吃东西，精神很差。"),
    ]

    all_results = []
    for name, recording in test_recordings:
        print(f"\n{'#' * 60}")
        print(f"# 测试场景：{name}")
        print(f"{'#' * 60}")
        print(f"护工录音：{recording}")
        start = time.perf_counter()
        result = run_pipeline(recording)
        elapsed = time.perf_counter() - start
        print_result(result)
        print(f"\n⏱ 本场景耗时：{elapsed:.2f}s")
        all_results.append((name, result, elapsed))

    print_summary(all_results)
```

> **2026 import 提醒：** `create_agent` 从 `langchain.agents`，`@tool` 从 `langchain.tools`，`init_chat_model` 从 `langchain.chat.models`，`StateGraph/END/START` 从 `langgraph.graph`，`InMemorySaver` 从 `langgraph.checkpoint.memory`。别用过时的 `initialize_agent` 或 `from langgraph.graph import StateGraph` 之外的旧路径。

代码要点解读：

1. **每个子 Agent 独立 checkpointer**：`build_xxx_agent()` 里每个 `create_agent` 都 `new` 了一个 `InMemorySaver()`，子 Agent 的推理过程留在自己实例里，不串进 Supervisor 的 State——这就是上下文隔离。
2. **State 只存结论不存过程**：`OrchestratorState` 的每个字段都是子 Agent 的"结论"（JSON 或文本），不是 messages 列表。Supervisor 不背子 Agent 的推理包袱。
3. **fan-out 并行**：`graph.add_edge("extract", "anomaly")` 和 `graph.add_edge("extract", "trend")` 让异常和趋势在同一个 superstep 并行跑，省一半时间。
4. **barrier 汇合**：anomaly 和 trend 都指向 advice，LangGraph 自动让 advice 等两个上游都完成才执行——步骤③的"汇总"。
5. **steps 用 add reducer**：异常和趋势并行时都往 `steps` 追加，必须 `Annotated[list, operator.add]`，否则并行写同一个 list 会冲突。
6. **重试 + 结构化解析兜底**：`invoke_with_retry` 给子 Agent 调用加失败重试，`safe_json_load` + `parse_model` 容错解析 LLM 的 JSON 输出，解析失败降级而非中断流水线——对应坑 3。
7. **彩蛋动态 Supervisor**：`build_dynamic_supervisor()` 是对比版本——主 Agent 也是 `create_agent`，五个子 Agent 包成 tool 由 LLM 决定调用顺序。固定流水线用静态 StateGraph，开放任务才用动态版。

> **前端类比：** 这套编排就像微前端的主应用路由——主应用（StateGraph）只管"现在渲染哪个子应用、子应用间怎么传 props"，子应用（子 Agent）的内部状态自己管。`steps` 字段就像主应用的事件总线日志，记录谁在什么时候产出了什么。

---

## 五、CrewAI vs LangGraph 对比（面试选型题）

### 5.1 为什么选 LangGraph Subagents 而不是 CrewAI

多 Agent 编排框架 2026 年最主流的两个选择是 **LangGraph**（LangChain 官方）和 **CrewAI**。养老场景我们选 LangGraph，理由是这套系统对"控制流确定性"和"可调试性"要求高——护工记录是固定流水线，不能让框架"自由发挥"。CrewAI 更偏"角色扮演式"协作，适合开放式任务（"几个 Agent 一起头脑风暴写报告"），对固定流水线的控制力反而弱。

### 5.2 四维对比表

| 维度 | LangGraph Subagents | CrewAI |
|------|---------------------|--------|
| **控制流** | 显式 StateGraph，节点+边，可精确控制并行/条件/循环；确定性高 | 声明式角色+任务，框架自动编排；控制力弱，靠 process 类型粗粒度切换 |
| **可调试性** | 高——每个节点状态可见，可断点、可回放（checkpointer）；LangSmith trace 树状展示 | 低——黑盒调度，出问题难定位是哪个 Agent 的责任 |
| **生态** | LangChain 官方，和 create_agent/MCP/RAG 无缝衔接；文档社区最大 | 独立生态，要自己适配模型/工具；社区活跃但小于 LangChain |
| **学习曲线** | 陡（要懂 StateGraph/节点/边/reducer）但掌握后可控性极强 | 平缓（定义 Agent+Task+Task 就跑）但天花板低 |
| **并行能力** | 原生 fan-out，节点级并行，精细 | 有 Process 并行，但粒度粗，复杂依赖难表达 |
| **2026 定位** | LangChain 官方推荐的多 Agent 标准方案 | 角色协作的轻量选择，非 LangChain 生态首选 |

### 5.3 选型决策一句话

- **任务流程固定、要确定性、要可调试** → LangGraph Subagents（养老记录系统选它）
- **任务开放、Agent 要自由协作、想快速搭原型** → CrewAI（如"三个 Agent 一起写市场分析报告"）

### 5.4 2026 年趋势

2026 年 LangChain 官方明确把 LangGraph 定位为多 Agent 编排的**推荐方案**——`create_agent` + LangGraph StateGraph 是官方文档主推的组合。CrewAI 仍活跃，但在 LangChain 生态里属于"可选的替代品"而非首选。面试时如果被问"你为什么用 LangGraph 不用 CrewAI"，核心论点是：**养老场景是固定流水线，要确定性控制和可调试性，LangGraph 的显式 StateGraph 比 CrewAI 的声明式角色协作更可控；且 LangGraph 是 LangChain 官方推荐，生态衔接好。**

---

## 动手实验

### 🟢 青铜：跑通 orchestrator.py

1. 把第四节完整代码存成 `orchestrator.py`
2. 配好 OpenAI API Key（或换成你用的模型）
3. 跑 `python orchestrator.py`，观察三个测试场景的输出
4. 重点看：异常和趋势是不是真的并行了（看日志里 ②A 和 ②B 的打印顺序）、severity 等级对不对、通知发给了谁

目标：从"五个独立模块"升级到"一个编排好的系统"，护工录一段音，一次跑出完整记录+建议+通知。

### 🟡 白银：加条件边，按 severity 走不同通知路径

现在通知 Agent 不管什么等级都走同一个节点。改成**条件边**：severity=critical 时跳过建议 Agent 直接通知（危急情况先通知再补建议），其他等级正常走建议→通知。

```python
# 提示：在 anomaly 之后加条件边
def route_by_severity(state: OrchestratorState) -> str:
    """critical 直奔 notify，否则走 advice。"""
    if state.get("severity") == "critical":
        return "notify"          # 危急：先通知
    return "advice"              # 正常/警告：先建议再通知

graph.add_conditional_edges("anomaly", route_by_severity,
                            {"notify": "notify", "advice": "advice"})
# 注意：critical 跳到 notify 时 trend 可能还在跑，思考怎么处理 advice_list 为空的情况
```

思考题：critical 跳过 advice 后，notify 节点拿不到 advice_list 怎么办？提示：通知 Agent 的 prompt 里处理"无建议时只通知异常"的情况。

### 🔴 王者：换成动态 Supervisor + 性能对比

1. 把 Supervisor 从"静态 StateGraph"换成"动态 LLM Supervisor"——主 Agent 也是 `create_agent`，五个子 Agent 包装成它的 tool，由 LLM 决定调用顺序
2. 对比两种方式：同一批录音，静态 vs 动态，哪个更快？更准？token 消耗少？
3. 用 LangSmith trace 看动态 Supervisor 每次推理"为什么调这个子 Agent"
4. 写对比报告：在 准确率/速度/token/可控性 上的差异，并给出"什么场景该用哪种"的结论

进阶：把异常和趋势的真并行用 `asyncio` 改成异步并发执行（LangGraph 的并行是 superstep 级，async 能更细粒度），测延迟提升。

---

## 踩坑记录 🕳️

### 坑 1：并行节点写同一个 State 字段，冲突报错

异常 Agent 和趋势 Agent 并行执行时，如果都往同一个非 reducer 字段写（比如都写 `messages`），LangGraph 会因为"同一 superstep 多次写入无 reducer 字段"报错或后写覆盖先写。

**解决：** 并行节点要么写不同字段（异常写 `anomalies`、趋势写 `trend_report`），要么用 `Annotated[list, operator.add]` 做 reducer 让并行写入自动合并。本代码的 `steps` 字段就是 add reducer。设计 State 时先想清楚"哪些字段会被并行写"。

### 坑 2：子 Agent 的 checkpointer 不独立，上下文串味

如果五个子 Agent 共享一个 `InMemorySaver()` 实例（图省事写成全局变量），它们的 messages 会混在一个 checkpointer 里——提取 Agent 能看到异常 Agent 的对话，隔离失效。

**解决：** 每个子 Agent 工厂函数里 `new` 自己的 `InMemorySaver()`，绝不共享。本代码每个 `build_xxx_agent()` 里都是独立实例。这是 Subagents 上下文隔离的物理基础。

### 坑 3：子 Agent 输出的 JSON 解析失败，下游全崩

子 Agent 偶尔输出多余文本或 markdown 包裹（如 `json` 代码块），`json.loads` 报错，`severity` 拿不到，notify 节点拿空值崩。

**解决：** 用 `with_structured_output` 强制 JSON（Week 03 学过）；或正则提取 `re.search(r'\{.*\}', text, re.DOTALL)`；解析失败时给默认值（severity 默认 normal）而不是中断流水线。养老场景宁可降级运行，也不能让一个子 Agent 解析失败拖垮整条流水线。

### 坑 4：barrier 节点拿不到上游字段（顺序写反）

advice 节点依赖 anomalies 和 trend_report，但如果 State 里这两个字段名拼错、或上游节点忘了 return 它们，advice 拿到空字符串，生成"无的放矢"的建议。

**解决：** 每个节点 return 的 key 必须和 State 定义、下游读取的 key 三处一致。建议用 TypedDict + IDE 类型检查。调试时在 advice_node 开头打印 `state["anomalies"]` 和 `state["trend_report"]` 确认非空。Week 07 Day 06 的"上下文检查插桩"在这里就用得上。

### 坑 5：并行执行其实是"伪并行"，没省时间

如果两个并行子 Agent 内部都是同步阻塞调用，Python GIL 下它们其实是交替执行而非真并行，延迟没省下来，只是顺序对调了。

**解决：** 真要省延迟，把子 Agent 调用改成 async（`ainvoke`），配合 `asyncio.gather` 真并发。LangGraph 的 superstep 并行保证了"逻辑上同时"，但物理并行要靠 async。养老场景延迟不敏感可先不管，实时性要求高时再上 async（王者实验方向）。

---

## 副线笔记：CrewAI vs LangGraph Subagents（面试选型题）

今天的副线是一道高频面试选型题：**"多 Agent 编排你选 CrewAI 还是 LangGraph？为什么？"** 这题考的不是背框架对比表，而是你能不能根据**任务特征**做技术选型。

### 选型决策框架

别死记"哪个好"，按任务特征走决策树：

```
你的任务流程是固定的，还是开放需要 LLM 临场决策？
├─ 固定流水线（提取→检测→通知） ──→ LangGraph StateGraph（确定性、可调试）
└─ 开放协作（几个 Agent 头脑风暴） ──→ 考虑 CrewAI（角色协作、快速原型）
    └─ 但如果在 LangChain 生态 ──→ 仍优先 LangGraph（生态衔接）

你的系统对可调试性要求高吗？
├─ 高（生产系统、要定位故障） ──→ LangGraph（节点可见、LangSmith trace）
└─ 低（一次性原型） ──→ CrewAI（快）
```

### 面试 Q&A 模板

> **Q：你做多 Agent 编排为什么选 LangGraph 而不是 CrewAI？**

**30 秒版：**

"我选 LangGraph 是因为养老记录系统是一条固定流水线——提取→异常→趋势→建议→通知，需要确定性控制和可调试性。LangGraph 的 StateGraph 用节点和边显式描述流程，能精确控制并行和汇合，每个节点状态可见、可回放，配合 LangSmith 能 trace 到是哪个子 Agent 出问题。CrewAI 是声明式角色协作，框架自动编排，对固定流水线控制力弱、出问题难定位。而且 LangGraph 是 LangChain 官方 2026 推荐的多 Agent 方案，和 create_agent、MCP、RAG 生态无缝衔接。"

**加分追问——"那 CrewAI 什么时候用？"**

"CrewAI 适合开放协作任务，比如'三个 Agent 分别从市场/技术/财务角度写报告再汇总'——任务不固定、要 Agent 自由发挥、快速搭原型时，CrewAI 的角色+任务声明式写法更省事。但生产系统、流程固定、要可调试的场景，我会选 LangGraph。两者不是谁替代谁，而是按任务特征选。"

### 三句金句

> "多 Agent 编排不是选'最强'的框架，是选'最匹配任务特征'的——固定流水线要确定性，开放协作要灵活性。"

> "LangGraph 的 StateGraph 就像手写 CI 流水线——每步节点可见、可断点、可回放；CrewAI 就像用现成的自动化平台——配个角色就跑，但内部黑盒。"

> "养老记录系统选 LangGraph 的硬理由：固定流水线 + 生产级可调试性 + LangChain 官方推荐，三个条件全中。"

### 今日观察任务

- 把今天的 `orchestrator.py` 跑通，用 LangSmith trace 看一次完整调用树，观察五个子 Agent 怎么在树里展开
- 重点确认：异常和趋势是不是真的并行了（在 trace 里看它们是否在同一层同时启动）
- 思考：如果要把这套编排接进 Day 01 的 FastAPI（成一个 `/api/record/process` 接口），Supervisor 该放 service 层还是单独的 orchestrator 层？

---

## 检查清单

- [ ] 理解单 Agent 塞五功能会导致上下文爆炸，多 Agent 编排通过上下文隔离解决
- [ ] 能用微前端类比讲清多 Agent 编排（子应用独立运行，主应用编排）
- [ ] 能说清 Week 07 四大模式里养老场景为什么选 Subagents（固定流水线+上下文隔离）
- [ ] 记住五个子 Agent 的职责分工和输入输出契约（提取/异常/趋势/建议/通知）
- [ ] 理解 Supervisor 用 StateGraph 实现的编排逻辑：提取→并行(异常+趋势)→建议→通知
- [ ] 跑通了 `orchestrator.py`，观察到异常和趋势的 fan-out 并行
- [ ] 知道并行节点写同字段要用 `Annotated[list, operator.add]` 做 reducer
- [ ] 知道每个子 Agent 要独立 checkpointer 才能上下文隔离
- [ ] 能回答面试选型题：LangGraph vs CrewAI，从控制流/可调试性/生态/学习曲线四维对比
- [ ] 理解静态 Supervisor（StateGraph）vs 动态 Supervisor（LLM Agent）的取舍

---

## 下课预告

> **Day 07 — 多模态处理（概念了解）+ 通知分发。** 今天我们把五天搭的模块编排成了一个能跑的完整系统。但养老场景还有个现实问题：护工不只录音，还会拍照——拍老人的伤口、拍饭盒、拍药盒。这些图片怎么进系统？明天学多模态处理的概念（Markdown 化 + Captioning + Select-then-Read），这是面试 Q17-Q20 的原理题，只学原理不做完整代码。同时把今天通知 Agent 的能力正式做成通知分发模块——按等级通知护工/家属/医生，接微信/短信渠道。本周从零件到系统的组装，在 Day 07 收尾。
