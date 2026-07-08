# Day 02 — AI Agent 结构化提取

## 学习目标

Day 01 我们把养老护工的微信录音喂给了腾讯云 ASR，拿到一坨口语化文本——"张奶奶今天体温三十七度八，血压高压一百五，早上喝了大半碗粥，精神还不错，就是有点咳嗽"。这坨文本对人来说一眼就懂，但对系统来说就是一滩无结构的字符串。今天我们要把这坨文本交给 AI Agent，提取成结构化的护工记录表单：老人姓名、生命体征、饮食情况、情绪状态、异常标记。这一步是整个养老记录系统的"咽喉"——提取不准，后面所有趋势分析、异常预警全是空中楼阁。

学完今天你能：

1. 对比 Week 03 手写 Agent Loop（while 循环 + tool_calls 手动 dispatch）和 Week 06 的 `create_agent`，说清两者在养老场景下的取舍
2. 用 `create_agent` + `@tool` + `system_prompt` 搭建一个养老记录提取 Agent，并能解释 `response_format` 如何让 Agent 直接吐出 Pydantic 对象
3. 设计 `CareRecord` Pydantic 模型，覆盖老人信息、生命体征、饮食、情绪、异常标记，并掌握字段校验与异常阈值的自动标记逻辑
4. 跑通完整的 `extraction_agent.py`，把一段 ASR 文本变成结构化表单，并能定位"提取失败"时该查哪一层

---

## 一、项目回顾：从录音文本到结构化表单

### 1.1 Day 01 给我们留下了什么

Day 01 的 ASR 管线产出了这样的文本：

```
张奶奶，今天体温三十七度八，血压高压一百五低压九十五，心率八十五。
早上喝了大半碗粥，中午没怎么吃。精神状态还行，有点咳嗽，情绪比昨天好一些。
护工小李记录。
```

护工在微信里说话是随性的——顺序乱、单位乱、口语化（"大半碗""还行"）。但下游系统需要的是这样一张表：

| 字段 | 值 |
|------|-----|
| 老人姓名 | 张奶奶 |
| 体温 | 37.8 ℃ |
| 血压（收缩/舒张） | 150 / 95 mmHg |
| 心率 | 85 bpm |
| 饮食情况 | 早餐大半碗粥，午餐未进食 |
| 情绪状态 | 较昨日好转 |
| 异常标记 | 体温偏高 + 收缩压偏高 |

从左边到右边，就是今天的全部工作。

### 1.2 为什么不用正则，要用 Agent

你可能会想：体温不就是正则 `\d+\.?\d*度` 吗？血压不就是 `\d+/\d+` 吗？

短期看正则快，但养老场景有三个坑正则兜不住：

| 坑 | 正则的表现 | Agent 的表现 |
|----|-----------|-------------|
| 口语化数字 | "三十七度八"正则匹不到 | LLM 理解中文数字，转成 37.8 |
| 上下文消歧 | "精神还行"到底是好还是差？ | LLM 结合语境判断情绪档位 |
| 信息补全 | 护工没说心率，要不要标 null | LLM 区分"没测"和"正常" |

> **前端类比：** 这就像前端表单——你可以手写每个 input 的校验逻辑（正则派），也可以用 schema 驱动的表单库（Agent 派）。字段少时手写快，字段多且有语义关系时 schema 驱动赢。养老记录字段有十几个，且互相有阈值关系，正是 Agent 的主场。

---

## 二、回顾 Week 03 手写 Agent Loop

在动手写 create_agent 版本前，先回顾 Week 03 我们手写过什么，这样你才能体会框架替你封装了什么。

### 2.1 Week 03 的 Agent Loop 骨架

Week 03 的 `agent_loop.py` 核心是这个 while 循环：

```python
# Week 03 手写 Agent Loop 的核心骨架（回顾）
def run(self, user_input: str) -> str:
    messages = [
        {"role": "system", "content": self.system_prompt},
        {"role": "user", "content": user_input},
    ]
    for turn in range(self.max_turns):           # ← 手动控制轮数
        response = self.call_llm(messages)       # ← 手动拼 headers 调 API
        msg = response["choices"][0]["message"]
        messages.append(msg)

        if not msg.get("tool_calls"):             # ← 手动判断是否结束
            return msg.get("content", "")

        tool_msgs = self._execute_tool_calls(msg["tool_calls"], messages)
        messages.extend(tool_msgs)                # ← 手动追加 tool 结果
    return "达到最大轮数"
```

这段代码能让你看清 Agent 的本质——LLM 思考 → 决定调工具 → 执行 → 把结果喂回 LLM → 直到 LLM 给出最终文本。但它有四个痛点（Week 06 Day 01 详细讲过）：模型切换改大段代码、工具绑定手写 JSON Schema、多轮对话无状态、缺少中间件层。

### 2.2 如果用 Week 03 的方式做提取

假设我们硬要用 Week 03 的 `ToolAgent` 做今天的提取任务，大概要写这些：

1. 手写一个 `extract_care_record` 工具的 JSON Schema（十几个字段，嵌套两层）
2. 手写一个 handler 函数把 LLM 返回的 arguments 解析成 dict
3. 手写循环判断"LLM 到底提取完了没有"
4. 手动从 `tool_calls[0].function.arguments` 里 `json.loads` 再塞进 Pydantic

光是第 1 步的 JSON Schema 就有几十行，而且换字段就要重写。Week 06 的 `create_agent` + `response_format` 把这四步全吞了。

---

## 三、Pydantic 模型设计：CareRecord

### 3.1 模型结构总览

提取结果的核心是 `CareRecord`，它嵌套三个子模型：

```
CareRecord
├── 老人信息
│   ├── name: str          # 老人姓名
│   └── room: str | None    # 房间号
├── 生命体征 Vitals
│   ├── temperature: float | None   # 体温 ℃
│   ├── systolic: int | None        # 收缩压 mmHg
│   ├── diastolic: int | None       # 舒张压 mmHg
│   └── heart_rate: int | None      # 心率 bpm
├── 饮食情况 Diet
│   ├── breakfast: str | None
│   ├── lunch: str | None
│   ├── dinner: str | None
│   └── appetite: str        # 好/一般/差
├── 情绪状态 emotion: str    # 平静/焦虑/低落/烦躁/好转
├── 备注 notes: str | None
└── 异常标记 anomalies: list[str]   # 自动填充
```

> **前端类比：** 这个结构就像前端的 TypeScript interface。你先定义好类型，下游所有代码（入库、趋势分析、前端渲染）都能享受类型推断。Pydantic 之于 Python，就是 TypeScript 之于 JS——单源真理，改一处全链路感知。

### 3.2 CareRecord 完整定义

```python
"""care_record.py — 养老护工记录的 Pydantic 模型"""
from typing import Optional
from pydantic import BaseModel, Field, field_validator, model_validator


class Vitals(BaseModel):
    """生命体征"""
    temperature: Optional[float] = Field(default=None, description="体温，单位℃")
    systolic: Optional[int] = Field(default=None, description="收缩压（高压），单位mmHg")
    diastolic: Optional[int] = Field(default=None, description="舒张压（低压），单位mmHg")
    heart_rate: Optional[int] = Field(default=None, description="心率，单位bpm")

    @field_validator("temperature")
    @classmethod
    def check_temp(cls, v):
        # 体温合理范围 30~45℃，超出说明 LLM 提取错了
        if v is not None and not (30 <= v <= 45):
            raise ValueError(f"体温 {v} 不在合理范围 30~45℃")
        return v


class Diet(BaseModel):
    """饮食情况"""
    breakfast: Optional[str] = Field(default=None, description="早餐进食情况")
    lunch: Optional[str] = Field(default=None, description="午餐进食情况")
    dinner: Optional[str] = Field(default=None, description="晚餐进食情况")
    appetite: str = Field(default="未说明", description="食欲：好/一般/差/未说明")


class CareRecord(BaseModel):
    """养老护工记录——Agent 提取的最终产物"""
    name: str = Field(description="老人姓名")
    room: Optional[str] = Field(default=None, description="房间号")
    vitals: Vitals = Field(default_factory=Vitals, description="生命体征")
    diet: Diet = Field(default_factory=Diet, description="饮食情况")
    emotion: str = Field(default="未说明", description="情绪状态")
    notes: Optional[str] = Field(default=None, description="其他备注")
    anomalies: list[str] = Field(default_factory=list, description="异常标记列表")

    @model_validator(mode="after")
    def auto_flag_anomalies(self):
        """模型级校验：自动标记异常项"""
        flags = []
        v = self.vitals
        if v.temperature is not None and v.temperature > 37.5:
            flags.append(f"体温偏高({v.temperature}℃)")
        if v.systolic is not None and v.systolic > 140:
            flags.append(f"收缩压偏高({v.systolic}mmHg)")
        if v.diastolic is not None and v.diastolic > 90:
            flags.append(f"舒张压偏高({v.diastolic}mmHg)")
        if v.heart_rate is not None and v.heart_rate > 100:
            flags.append(f"心率过快({v.heart_rate}bpm)")
        if v.heart_rate is not None and v.heart_rate < 50:
            flags.append(f"心率过慢({v.heart_rate}bpm)")
        if self.diet.appetite == "差":
            flags.append("食欲差")
        # 保留 LLM 可能已经标记的异常，合并去重
        existing = set(self.anomalies)
        for f in flags:
            if f not in existing:
                self.anomalies.append(f)
        return self
```

这里有两个关键设计：

**`field_validator`（字段级校验）：** 体温不在 30~45℃ 直接报错。这不是业务异常，是防 LLM 瞎提取——比如把"37 度 8"提取成 378。字段校验拦在第一道。

**`model_validator(mode="after")`（模型级校验 + 自动标记）：** 这是异常标记的核心。LLM 不需要自己判断"37.8 算不算发烧"——它只管忠实提取数值，阈值判断交给 Pydantic。这样做有三个好处：阈值改了只改一处、LLM 不会被医学知识干扰、异常标记逻辑可单元测试。

> **为什么不用 LLM 判断异常？** 因为阈值是规则，规则就该用代码写。让 LLM 判断"37.8 算不算发烧"，它会根据训练数据猜，有时 37.3 就标异常有时 37.8 还说正常。代码判断是确定性的，37.5 这条线画在哪就执行到哪。Agent 负责理解语义，Pydantic 负责执行规则，各司其职。

---

## 四、用 create_agent 搭建提取 Agent

### 4.1 三个核心组件

搭建提取 Agent 需要三样东西，正好对应 `create_agent` 的三个核心参数：

| 组件 | 参数 | 养老场景的作用 |
|------|------|---------------|
| 模型 | `model` | 理解 ASR 文本语义，提取字段 |
| 工具 | `tools` | 辅助查询，比如查老人档案补全房间号 |
| 提示词 | `system_prompt` | 定义提取规则：提取哪些字段、缺失怎么填 |

额外加一个 `response_format=CareRecord`，让 Agent 直接输出 Pydantic 对象，而不是让你从文本里抠 JSON。

### 4.2 system_prompt 定义提取规则

```python
EXTRACT_SYSTEM_PROMPT = """你是养老护理记录提取助手。你的任务是从护工口述的录音文本中，提取结构化的护理记录。

提取规则：
1. 老人姓名：通常出现在开头，如"张奶奶""王大爷"
2. 体温：中文数字要转阿拉伯数字，如"三十七度八"→37.8
3. 血压：格式为"收缩压/舒张压"，如"高压一百五低压九十五"→150/95
4. 心率：单位 bpm，如"心率八十五"→85
5. 饮食：按早/中/晚分别记录，护工没说的餐填 null
6. 食欲：根据描述判断 好/一般/差/未说明
7. 情绪：从"精神还行""情绪低落""比昨天好"等描述归纳为：平静/焦虑/低落/烦躁/好转
8. 异常标记：你不需要判断异常，只管忠实提取数值，系统会自动标记
9. 没提到的字段填 null，不要编造

如果需要查询老人档案补全房间号，可以使用 query_elder_archive 工具。"""
```

注意第 8 条——明确告诉 LLM"不用判断异常"。这和第三节的 `auto_flag_anomalies` 呼应：LLM 只管提取，阈值判断交给代码。

### 4.3 @tool 定义辅助工具

提取 Agent 不一定需要工具，但养老场景有个典型需求：护工口述时常常不提房间号，需要查档案补全。我们定义一个辅助工具：

```python
from langchain.tools import tool

# 模拟老人档案库
ELDER_ARCHIVE = {
    "张奶奶": {"room": "302", "age": 82},
    "王大爷": {"room": "105", "age": 78},
    "李爷爷": {"room": "201", "age": 85},
}


@tool
def query_elder_archive(name: str) -> str:
    """查询老人档案，补全房间号等信息。

    当护工口述中提到了老人姓名但没提房间号时使用此工具。
    name 为老人姓名。
    """
    info = ELDER_ARCHIVE.get(name)
    if info:
        return f"姓名:{name} 房间:{info['room']} 年龄:{info['age']}"
    return f"未找到 {name} 的档案记录"
```

`@tool` 装饰器做了 Week 03 要手写的事——从函数签名和 docstring 自动推断 JSON Schema。你写好 docstring（尤其"什么时候用"），模型就知道该不该调这个工具。

> **前端类比：** `@tool` 就像 React 里的 `forwardRef`——一个装饰器/高阶函数，把你的普通函数"升级"成框架能理解的组件。你只管写业务逻辑，schema 生成、参数校验、错误捕获框架全包了。

---

## 五、结构化输出：response_format + with_structured_output

### 5.1 两种结构化输出方式

Week 03 Day 04 我们学过结构化输出的四种方式（Prompt 指令法 / JSON Mode / Function Calling / Constrained Decoding）。今天用 2026 年最推荐的方式——`create_agent` 的 `response_format` 参数。

| 方式 | 代码 | 输出位置 | 适合场景 |
|------|------|---------|---------|
| `create_agent` + `response_format` | 一行参数 | `result["structured_response"]` | 有工具循环的 Agent |
| `model.with_structured_output()` | 链式调用 | 直接返回 Pydantic 对象 | 纯提取，无工具循环 |

两者底层是同一套机制——`response_format` 传入 Pydantic 模型后，`create_agent` 内部会调用 `model.with_structured_output(CareRecord)`，把 schema 绑定到模型上。区别只是 `create_agent` 多了工具循环能力。

### 5.2 为什么用 response_format 而不是让 LLM 自己吐 JSON

```python
# ❌ Week 03：从 messages 里抠文本，正则碰运气
text = result["messages"][-1].content          # 可能带 ```json 的文本
match = re.search(r'\{.*\}', text, re.DOTALL)  # 正则碰运气
record = CareRecord.model_validate_json(match.group())  # 可能炸

# ✅ 2026：response_format=CareRecord 后，直接拿 Pydantic 实例
record = result["structured_response"]  # 直接是 CareRecord，不用解析
```

`response_format` 内部有两条策略（`AutoStrategy` 自动选）：**ProviderStrategy**（模型原生支持，如 OpenAI 的 json_schema 模式）和 **ToolStrategy**（模型不支持时，把 schema 包成"输出工具"强制 LLM 调用返回结构化结果）。你不用管走哪条，`create_agent` 自动判断——本地 Ollama 通常走 ToolStrategy，OpenAI 走 ProviderStrategy。

---

## 六、完整 extraction_agent.py

下面是完整的、可运行的提取 Agent。模型定义（Vitals/Diet/CareRecord）见第三节，工具和提示词见第四节，这里把它们组装起来——这才是"完整文件"的增量部分：

```python
"""extraction_agent.py — 养老护工记录结构化提取 Agent

功能：把 ASR 转录的护工口述文本，提取成 CareRecord 结构化表单。
依赖：langchain, langgraph, pydantic, ollama（或换成 openai）
运行：python extraction_agent.py
"""
from uuid import uuid4

from langchain.agents import create_agent
from langchain.tools import tool
from langchain.chat_models import init_chat_model
from langgraph.checkpoint.memory import InMemorySaver

# 复用第三节的 Pydantic 模型：Vitals / Diet / CareRecord（含 auto_flag_anomalies）
# 复用第四节的 query_elder_archive 工具和 EXTRACT_SYSTEM_PROMPT


# ============================================================
# 创建提取 Agent
# ============================================================

def build_extraction_agent(model: str = "ollama:qwen2.5:7b"):
    """创建养老记录提取 Agent。

    model 可以是 "ollama:qwen2.5:7b"（本地免费）或 "openai:gpt-4o"（云端更准）。
    用 init_chat_model 显式初始化模型，也可以直接把字符串传给 create_agent。
    """
    llm = init_chat_model(model)           # 统一模型接口，切换供应商只改字符串
    return create_agent(
        model=llm,
        tools=[query_elder_archive],
        system_prompt=EXTRACT_SYSTEM_PROMPT,
        response_format=CareRecord,       # 结构化输出：直接吐 Pydantic 对象
        checkpointer=InMemorySaver(),    # 会话持久化（为 Day 03 反思模式预留）
    )


# ============================================================
# 运行 + 展示
# ============================================================

def extract_and_print(agent, asr_text: str, case_name: str = ""):
    """运行提取并格式化打印结果"""
    config = {"configurable": {"thread_id": f"extract-{uuid4()}"}}
    print(f"\n{'='*60}")
    if case_name:
        print(f"案例：{case_name}")
    print(f"ASR 文本：{asr_text}")
    print(f"{'='*60}")

    result = agent.invoke(
        {"messages": [{"role": "user", "content": asr_text}]},
        config=config,
    )

    # 直接拿到 CareRecord 实例（不用从文本抠 JSON）
    record: CareRecord = result["structured_response"]

    v, d = record.vitals, record.diet
    print(f"\n姓名：{record.name}  房间：{record.room or '(未查到)'}")
    print(f"生命体征：体温={v.temperature}℃  血压={v.systolic}/{v.diastolic}  心率={v.heart_rate}")
    print(f"饮食：早={d.breakfast}  中={d.lunch}  晚={d.dinner}  食欲={d.appetite}")
    print(f"情绪：{record.emotion}")
    if record.notes:
        print(f"备注：{record.notes}")
    print(f"异常标记：{record.anomalies if record.anomalies else '无异常'}")

    # 如果走了工具，打印工具调用过程
    tool_msgs = [m for m in result["messages"] if m.type == "tool"]
    for tm in tool_msgs:
        print(f"  [工具] {tm.name}: {tm.content}")


if __name__ == "__main__":
    agent = build_extraction_agent(model="ollama:qwen2.5:7b")
    # 没装 ollama 的话换成：build_extraction_agent(model="openai:gpt-4o")

    # 测试 1：异常记录（体温+血压双高）
    extract_and_print(agent,
        "张奶奶，今天体温三十七度八，血压高压一百五低压九十五，心率八十五。"
        "早上喝了大半碗粥，中午没怎么吃。精神状态还行，有点咳嗽，情绪比昨天好一些。"
        "护工小李记录。",
        "异常记录（体温+血压偏高）")

    # 测试 2：正常记录
    extract_and_print(agent,
        "王大爷今天状态不错，体温三十六度五，血压一百二十八十，心率七十二。"
        "三餐都正常吃了，胃口挺好，情绪平静。",
        "正常记录")

    # 测试 3：信息缺失
    extract_and_print(agent, "李爷爷今天体温正常，吃了饭，精神一般。", "信息缺失")
```

**预期输出（测试 1）：**

```
姓名：张奶奶  房间：302
生命体征：体温=37.8℃  血压=150/95  心率=85
饮食：早=大半碗粥  中=null  晚=null  食欲=一般
情绪：好转
备注：有点咳嗽
异常标记：['体温偏高(37.8℃)', '收缩压偏高(150mmHg)', '舒张压偏高(95mmHg)']

[工具调用 1 次]
  → query_elder_archive: 姓名:张奶奶 房间:302 年龄:82
```

注意两点：房间号是 Agent 自动调 `query_elder_archive` 补全的；异常标记是 Pydantic 的 `auto_flag_anomalies` 自动算出来的，LLM 完全没参与阈值判断。

---

## 七、对比表：Week 03 手写 vs Week 06 create_agent

把同一个"养老记录提取"任务，分别用 Week 03 和 Week 06 的方式实现，差异一目了然：

| 维度 | Week 03 手写 Agent Loop | Week 06 create_agent |
|------|------------------------|----------------------|
| **代码量** | ~120 行（ToolAgent 类 + schema + dispatch + 循环） | ~60 行（模型定义 + 工具 + 一行 create_agent） |
| **工具定义** | 手写 JSON Schema dict + handler 注册表 | `@tool` 装饰器自动推断 |
| **结构化输出** | 从 `tool_calls[0].function.arguments` 手动 `json.loads` + Pydantic 验证 | `response_format=CareRecord` 一行，直接拿 Pydantic 实例 |
| **异常标记** | 要在循环外手动调 `record.auto_flag_anomalies()` 或在 handler 里写 | Pydantic `model_validator` 自动触发，Agent 无感 |
| **多轮对话** | 手动维护 messages 列表，进程重启全丢 | `checkpointer=InMemorySaver()` + `thread_id` 自动管理 |
| **模型切换** | 改 `call_llm` 的 headers/payload，大改 | 改一个字符串 `"ollama:..."` → `"openai:..."` |
| **错误处理** | 手写 try/except + 循环检测 + max_turns | LangGraph 内置错误处理 + recursion_limit |
| **可维护性** | 加字段要改 schema + handler + 验证三处 | 加一个 Pydantic 字段，schema/验证全自动 |
| **功能性** | 能跑，但只有基础循环 | 持久化、流式、中间件、人机交互全有 |

> **核心结论：** Week 03 手写让你"懂原理"，Week 06 create_agent 让你"出活快"。养老项目是工程项目不是教学 demo，果断用 create_agent。但你得手写过 Week 03，才知道 `response_format` 底层帮你省了哪几十行——这就是为什么本课程先手写再上框架。

---

## 动手实验

### 🟢 青铜：跑通 extraction_agent.py

1. 确保 Ollama 拉了 `qwen2.5:7b`（`ollama pull qwen2.5:7b`），或换成你有 key 的 `openai:gpt-4o`
2. 运行 `python extraction_agent.py`，验证三个测试案例都能正确提取
3. 重点观察：测试 1 的异常标记是否正确标了"体温偏高+收缩压偏高+舒张压偏高"

### 🟡 白银：扩展模型 + 调阈值

1. 在 `CareRecord` 里加一个 `medication: Optional[str]`（用药情况）字段，在 `EXTRACT_SYSTEM_PROMPT` 里加提取规则，验证 Agent 能提取"今天吃了降压药"
2. 把体温异常阈值从 37.5 改成 37.3，重跑测试 1，观察异常标记变化
3. 换一个模型（ollama → openai 或反过来），对比两个模型对"三十七度八"这种中文数字的提取准确率

### 🔴 王者：批量提取 + 质量评估

1. 写 5 段不同风格的护工口述文本（有的信息全、有的缺失多、有的口语化严重），做成 mini 测试集
2. 写一个 `batch_extract` 函数，批量跑提取，统计：字段缺失率、异常标记准确率、平均耗时
3. 对比 `response_format` 和 Week 03 的 JSON Mode 方式：同一个文本各跑 5 次，统计字段提取一致率
4. 思考：哪些字段 LLM 容易提错？是数值类（体温/血压）还是语义类（情绪/食欲）？为什么？

---

## 踩坑记录 🕳️

### 坑 1：response_format 返回的 structured_response 取不到

```python
# ❌ 从 messages 最后一条抠内容（Week 03 旧习惯）
record = result["messages"][-1].content  # 可能是空字符串或一段总结文本

# ✅ 从 structured_response 取（2026 新方式）
record = result["structured_response"]   # 直接是 CareRecord 实例
```

**原因：** `response_format` 生成的结构化输出不放在 `messages` 的 content 里，而是单独放在 state 的 `structured_response` 字段。这是 Week 03 没有的概念——手写 Agent 时所有输出都在 messages 里。如果你发现 `content` 是空的，先检查是不是该取 `structured_response`。

### 坑 2：本地小模型中文数字提取不准

"三十七度八"在 qwen2.5:7b 上有时提取成 37.8，有时提取成 378（漏了小数点），有时直接 null。

**解决：** 三管齐下——
1. `system_prompt` 里给正例："三十七度八→37.8"（少样本提示）
2. Pydantic `field_validator` 拦截不合理范围（378 直接报错，触发重试）
3. 关键场景换 `openai:gpt-4o` 或 `qwen2.5:14b`，7B 是中文数字提取的及格线

### 坑 3：Agent 不调工具直接输出

护工没提房间号时，期望 Agent 调 `query_elder_archive` 补全，但 Agent 直接输出了 `room=null`。

**解决：** Week 06 Day 01 讲过，这是最典型的 Agent 失败模式。三个原因：模型太弱（换 7B+）、system_prompt 没明确说"护工没提房间号时用工具查询"（加上这句）、工具 docstring 没写清"什么时候用"（补上"当护工没提房间号时使用"）。本地小模型尤其需要在 prompt 里反复强调工具使用时机。

### 坑 4：Pydantic 校验报错导致整个 Agent 崩

LLM 提取的体温是 378（漏小数点），`field_validator` 抛 `ValueError`，整个 `invoke` 直接抛异常崩掉。

**解决：** `create_agent` 内部会捕获 Pydantic 校验错误并反馈给 LLM 重试，但前提是你用 `response_format`（走 ToolStrategy 时校验失败会自动重试）。如果手动解析，要自己包 `try/except ValidationError` 把错误信息喂回 LLM 让它修正。

### 坑 5：情绪字段 LLM 归纳不一致

同一段"精神还行"，有时归纳成"平静"有时归纳成"好转"。因为 system_prompt 里没给情绪档位的明确定义。

**解决：** 在 prompt 里给每个档位的定义：平静=精神正常无明显波动、好转=比之前好（如"比昨天好一些"）、低落=精神差不想说话、焦虑=烦躁不安、烦躁=情绪激动不配合。LLM 有了明确定义，归纳一致性显著提升。这和前端写枚举注释一个道理——把"你觉得呢"变成"按这个标准判断"。

---

## 副线笔记

### Week 03 手写 vs Week 06 create_agent：什么时候该手写

今天我们把同一个提取任务用两种方式都过了一遍，结论很明确：工程项目用 `create_agent`。但副线的问题是——什么时候你还得回去手写 Week 03 那套 while 循环？

**答案：当你需要的控制流超出标准 ReAct 循环时。**

`create_agent` 内部的图是固定的：`model → (有 tool_calls?) → tools → model → ... → END`，覆盖 90% 的 Agent 场景。但提取失败自动重试、提取结果过 Critic 审查（明天 Day 03 的 Reflection）、并行提取多老人再合并、条件分支（短文本走轻量提取/长文本走分段）——这些自定义控制流，`create_agent` 的固定图就不够用了，要么用 middleware 拦截，要么退回 Week 06 Day 04 手写 `StateGraph`。

> **但注意：** 手写 StateGraph 不等于退回 Week 03。Week 06 Day 04 的手写图用的是 `StateGraph` + `ToolNode` + `tools_condition`，比 Week 03 的裸 while 循环高一个抽象层。Week 03 是"手搓引擎"，Week 06 手写图是"用零件组装引擎"，`create_agent` 是"买整车"。三层抽象，按需选择。

### 前端类比：三层抽象

| Agent 层级 | 前端类比 | 控制权 |
|-----------|---------|--------|
| Week 03 手写 while 循环 | 原生 JS 手写事件循环 | 全在手，全得自己写 |
| Week 06 手写 StateGraph | 用 React 但手写 reducer | 图自己搭，节点组件复用 |
| Week 06 create_agent | 用 Next.js 全栈框架 | 框架定流程，你填业务 |

养老项目里，Day 02 提取用 `create_agent`，Day 03 反思就要手写 StateGraph 加 Critic 节点——这就是层级选择。

### 今日观察任务

- 把 `extraction_agent.py` 跑一遍，记录哪些字段容易提错
- 让 Claude Code 审查你的 `system_prompt` 和 `@tool` docstring，问它"哪些规则不够明确"
- 对比 `create_agent` 版本和 Week 03 的 `ToolAgent`，你少写了多少行"胶水代码"

---

## 检查清单

- [ ] 理解 Day 01 的 ASR 文本到结构化表单的 gap，为什么正则不够用
- [ ] 能说出 Week 03 手写 Agent Loop 的四个痛点（模型切换/工具绑定/无状态/无中间件）
- [ ] 设计了完整的 `CareRecord` Pydantic 模型，包含 Vitals/Diet 子模型
- [ ] 理解 `field_validator`（字段级）和 `model_validator`（模型级）的区别和用途
- [ ] 异常标记逻辑用 `auto_flag_anomalies` 实现，阈值改一处全链路生效
- [ ] 用 `create_agent` + `response_format=CareRecord` + `@tool` + `InMemorySaver` 搭建了提取 Agent
- [ ] 知道从 `result["structured_response"]` 取结构化输出，而不是从 messages 抠
- [ ] 跑通 `extraction_agent.py`，验证异常记录的标记正确（体温+血压偏高）
- [ ] 对比表能说清 Week 03 手写 vs Week 06 create_agent 的取舍

---

## 下课预告

> **Day 03 — Reflection/Self-Correction 模式。** 今天提取 Agent 能把文本变成结构化表单了，但提取一定准吗？"三十七度八"会不会被提成 37.3？护工说"没吃午饭"会不会被标成"食欲差"？明天我们给提取结果加一层"审查"——Critic Agent 检查提取结果的完整性和一致性，发现问题反馈给提取 Agent 自我纠正。这正是面试高频 Q8（Reflection 模式）的核心。你会学到：怎么用 LangGraph 手写 Critic 节点（今天 create_agent 的固定图不够用了，该上手写 StateGraph 了）、反思循环怎么避免无限重试、Reflection 在养老场景的真实价值。
