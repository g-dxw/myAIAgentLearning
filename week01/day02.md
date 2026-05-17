# Day 02 — Pydantic v2 数据校验

## 学习目标

掌握 Pydantic v2 的核心用法，理解它和 dataclass / TypedDict 的区别，能写出 Agent 项目中常用的配置模型和请求验证。

---

## 一、为什么需要 Pydantic

回顾 Day 01 学过的三种定义数据结构的方式：

| 方式 | 运行时校验 | JSON 序列化 | 适用场景 |
|------|-----------|------------|---------|
| `dataclass` | ❌ 不校验 | ❌ 需手动 | 内部数据传递 |
| `TypedDict` | ❌ 不校验 | ❌ 需手动 | 纯类型标注 |
| **Pydantic v2** | ✅ 自动校验+转换 | ✅ 内置 | **API 边界、配置、LLM 结构化输出** |

```python
# dataclass 的陷阱：类型标注只是"建议"，运行时不管
from dataclasses import dataclass

@dataclass
class User:
    name: str
    age: int

User(name=123, age="not a number")  # 不报错！运行时完全不管类型
# User(name=123, age='not a number')  ← 这也能通过

# Pydantic：运行时严格校验
from pydantic import BaseModel

class User(BaseModel):
    name: str
    age: int

User(name=123, age="not a number")
# ValidationError: name → str 类型不匹配; age → 无法转为 int
```

**Agent 项目中最该用 Pydantic 的 3 个位置：**
1. API 请求体 / 响应模型（FastAPI 原生集成）
2. LLM 结构化输出的 Schema 定义
3. 配置管理（读取环境变量 / YAML，自动校验）

---

## 二、基础用法

### 2.1 BaseModel + 基本字段

```python
from pydantic import BaseModel
from typing import Literal

class Message(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str

# 创建实例
msg = Message(role="user", content="北京天气怎么样？")
print(msg.model_dump())  # {"role": "user", "content": "北京天气怎么样？"}
```

### 2.2 Field —— 给字段加约束和元信息

```python
from pydantic import BaseModel, Field

class AgentConfig(BaseModel):
    model: str = Field(default="claude-sonnet-4-6", description="模型名称")
    max_tokens: int = Field(default=4096, ge=1, le=32000, description="最大输出 token")
    temperature: float = Field(default=0.7, ge=0, le=1)
    system_prompt: str = Field(min_length=1)

# 缺省值自动填充
config = AgentConfig(system_prompt="你是一个有用的助手")
print(config.model)  # "claude-sonnet-4-6"（用默认值）

# 超限会报错
AgentConfig(system_prompt="", max_tokens=999999)
# ValidationError: max_tokens ≤ 32000; system_prompt 长度不足
```

**Field 常用参数速查：**

| 参数 | 作用 | 示例 |
|------|------|------|
| `default` | 默认值 | `default=4096` |
| `ge` / `le` | ≥ / ≤ | `ge=1, le=10` |
| `gt` / `lt` | > / < | `gt=0` |
| `min_length` / `max_length` | 字符串长度限制 | `min_length=1` |
| `pattern` | 正则匹配 | `pattern=r"^[a-z_]+$"` |
| `description` | 字段说明（给 LLM 看） | `description="用户名称"` |

### 2.3 嵌套模型

```python
class Usage(BaseModel):
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0

class AgentResult(BaseModel):
    model: str
    content: str
    usage: Usage                       # 嵌套 Pydantic 模型
    stop_reason: Literal["end_turn", "tool_use", "max_tokens"]

# 传入嵌套 dict，自动解析
raw = {
    "model": "claude-opus-4-7",
    "content": "你好",
    "usage": {"input_tokens": 15, "output_tokens": 3},
    "stop_reason": "end_turn",
}
result = AgentResult(**raw)
print(result.usage.input_tokens)  # 15
```

---

## 三、验证器（Validator）

Pydantic v2 的验证器用 `@field_validator` 和 `@model_validator`。

### 3.1 field_validator —— 单字段校验 + 转换

```python
from pydantic import BaseModel, field_validator

class CareRecord(BaseModel):
    blood_pressure: str | None = None  # 原始输入可能是 "145/90"

    @field_validator("blood_pressure", mode="before")  # before = 在类型校验前执行
    @classmethod
    def normalize_bp(cls, v: str | None) -> str | None:
        """将各种 BP 写法归一化"""
        if v is None:
            return None
        # "145/90" → "145/90"，"145 90" → "145/90"，"145 over 90" → "145/90"
        import re
        cleaned = re.sub(r"\s*over\s*|\s+", "/", v)
        return cleaned

# 测试
record = CareRecord(blood_pressure="145 over 90")
print(record.blood_pressure)  # "145/90"
```

### 3.2 转换型验证器 —— 自动类型转换

```python
class ToolCall(BaseModel):
    name: str
    input: dict

    @field_validator("input", mode="before")
    @classmethod
    def parse_json_string(cls, v):
        """如果 input 是 JSON 字符串，自动解析"""
        if isinstance(v, str):
            import json
            return json.loads(v)
        return v

# 两种输入都能处理
ToolCall(name="search", input='{"query": "天气"}')  # JSON 字符串 → 自动解析
ToolCall(name="search", input={"query": "天气"})    # dict → 保持不变
```

### 3.3 model_validator —— 跨字段校验

```python
from pydantic import model_validator
from typing import Self

class ConversationConfig(BaseModel):
    max_turns: int = 10
    max_tokens_per_turn: int = 4096
    total_budget_tokens: int = 100000

    @model_validator(mode="after")
    def check_token_budget(self) -> Self:
        """确保单轮 token × 轮次 不超出总预算"""
        estimated = self.max_tokens_per_turn * self.max_turns
        if estimated > self.total_budget_tokens:
            raise ValueError(
                f"预算超出：{self.max_turns}轮×{self.max_tokens_per_turn}tokens "
                f"= {estimated} > 总预算 {self.total_budget_tokens}"
            )
        return self

# ConversationConfig(max_turns=30, max_tokens_per_turn=4096, total_budget_tokens=50000)
# ValidationError: 预算超出
```

---

## 四、模型导出 —— Agent 代码里的高频操作

```python
from pydantic import BaseModel

class ToolSchema(BaseModel):
    name: str
    description: str
    parameters: dict

tool = ToolSchema(
    name="get_weather",
    description="查询指定城市的天气",
    parameters={
        "type": "object",
        "properties": {"city": {"type": "string"}},
        "required": ["city"]
    }
)

# 1. 导出为 dict
tool.model_dump()
# {'name': 'get_weather', 'description': '查询指定城市的天气', 'parameters': {...}}

# 2. 导出为 JSON 字符串
tool.model_dump_json()
# '{"name":"get_weather","description":"查询指定城市的天气","parameters":{...}}'

# 3. model_dump 常用参数
tool.model_dump(exclude={"parameters"})          # 排除字段
tool.model_dump(include={"name", "description"}) # 只包含指定字段
tool.model_dump(exclude_none=True)               # 排除 None 值
tool.model_dump(exclude_unset=True)              # 排除未设置的字段（只保留显式传入的）
```

---

## 五、实战练习

### 练习 1：LLM 调用配置模型（15 min）

```python
from pydantic import BaseModel, Field
from typing import Literal

class LLMCallConfig(BaseModel):
    """一次 LLM 调用的完整配置"""
    model: str = Field(default="claude-sonnet-4-6")
    max_tokens: int = Field(default=4096, ge=1, le=32000)
    temperature: float = Field(default=0.7, ge=0, le=1)
    system: str = Field(min_length=1)
    stream: bool = False
    stop_reason_expected: list[Literal["end_turn", "tool_use", "max_tokens"]] = ["end_turn"]

# 测试：创建合法配置，然后故意设错参数看报错信息
```

### 练习 2：照护记录模型（20 min）

用 Pydantic 定义养老护工系统的照护表单模型，包含嵌套结构、Field 约束、自定义验证器：

```python
from pydantic import BaseModel, Field, field_validator
from typing import Literal

class VitalSigns(BaseModel):
    blood_pressure_systolic: int | None = Field(default=None, ge=60, le=250)
    blood_pressure_diastolic: int | None = Field(default=None, ge=30, le=150)
    heart_rate: int | None = Field(default=None, ge=30, le=220)
    temperature: float | None = Field(default=None, ge=35.0, le=42.0)

class Meal(BaseModel):
    meal_type: Literal["早餐", "午餐", "晚餐", "加餐"]
    content: str = Field(min_length=1)
    intake_percentage: int = Field(default=100, ge=0, le=100, description="进食比例 0-100%")

class Medication(BaseModel):
    name: str
    dosage: str
    time: str
    taken: bool = True

class CareForm(BaseModel):
    """护工照护表单 —— 对应 LLM 结构化输出的 Schema"""
    vital_signs: VitalSigns
    meals: list[Meal]
    fluid_intake_ml: int | None = Field(default=None, ge=0)
    medications: list[Medication] = []
    mental_status: str | None = None
    skin_condition: str | None = None
    pain_level: int | None = Field(default=None, ge=0, le=10)
    caregiver_notes: str | None = Field(default=None, max_length=500)

    @field_validator("pain_level", mode="before")
    @classmethod
    def normalize_pain(cls, v):
        """护工可能说 '疼得厉害' 而不是数字"""
        pain_map = {"无": 0, "轻微": 2, "中度": 5, "很疼": 8, "剧烈": 10}
        if isinstance(v, str):
            return pain_map.get(v, v)
        return v

# 测试：模拟 LLM 返回的结构化数据
mock_llm_output = {
    "vital_signs": {"blood_pressure_systolic": 145, "blood_pressure_diastolic": 90, "heart_rate": 78},
    "meals": [
        {"meal_type": "早餐", "content": "半碗粥 + 一个鸡蛋", "intake_percentage": 80},
    ],
    "fluid_intake_ml": 300,
    "pain_level": "中度",  # 字符串 → 自动转为 5
    "caregiver_notes": "情绪不错"
}

form = CareForm(**mock_llm_output)
print(form.model_dump())
print(f"疼痛评分: {form.pain_level}")  # 5
```

### 练习 3：用 Pydantic 生成 Claude Tool Schema（20 min）

这是 Agent 开发中的高频需求——用 Pydantic 模型自动生成 tool definition：

```python
from pydantic import BaseModel, Field
import json

class GetWeatherInput(BaseModel):
    """查询天气的参数"""
    city: str = Field(description="城市名称，如北京、上海")
    date: str | None = Field(default=None, description="日期，YYYY-MM-DD 格式，默认今天")

# Pydantic v2 内置 JSON Schema 生成
schema = GetWeatherInput.model_json_schema()
print(json.dumps(schema, ensure_ascii=False, indent=2))

# 直接作为 Claude tool 的 input_schema
tool_definition = {
    "name": "get_weather",
    "description": "查询指定城市的天气信息",
    "input_schema": GetWeatherInput.model_json_schema(),
}
```

---

## 六、Pydantic vs 其他方案 —— 选型决策

```
你的数据从哪来？
  ├── 完全在代码内部控制（内部函数传参）
  │     → dataclass 就够了，够轻
  │
  ├── 从外部来（HTTP 请求 / 用户输入 / 环境变量）
  │     → Pydantic BaseModel，必须校验
  │
  ├── 只是一堆函数的类型标注，不需要运行时行为
  │     → TypedDict
  │
  └── 传给 LLM 做 structured output
        → Pydantic BaseModel，因为 .model_json_schema() 直接能用
```

---

## Day 02 检查清单

- [ ] 能用 `BaseModel` + `Field` 定义带约束的数据模型
- [ ] 理解 Pydantic 和 dataclass 的核心区别（运行时校验 vs 纯标注）
- [ ] 能用 `@field_validator` 做单字段清洗和转换
- [ ] 能用 `@model_validator` 做跨字段校验
- [ ] 能用 `.model_dump()` / `.model_dump_json()` 导出数据
- [ ] 能用 `.model_json_schema()` 生成 JSON Schema 给 Claude 用
- [ ] 能写出嵌套模型（模型里包含另一个模型 / 模型列表）

## 踩坑记录

- [ ] 踩了什么坑 / 怎么解决的
- pip 版本不对，导致安装不了pydantic包 / 更新pip版本后解决
- vscode选择的 Python版本不对，我本地安装了多个Python包，引入的是非全局的python包 / 设置vscode的Python版本位置后解决

```
// 记录
```

## 明天计划

- [ ] Day 03 — FastAPI 路由 + 依赖注入
