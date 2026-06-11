# Day 04 — 结构化输出（JSON Mode）：让 LLM 说"机器听得懂的话"

## 学习目标

前三天我们让 LLM 调**工具**（Function Calling），今天反过来：**让 LLM 输出我们程序能直接用的数据结构**。

学完今天你能回答：
- 为什么不能直接让 LLM 说"给我 JSON"？坑在哪？
- JSON Mode、Function Calling、Constrained Decoding 到底有什么区别？
- 怎么用 Pydantic v2 把 LLM 的输出变成类型安全的 Python 对象？
- 生产环境中，信息提取、文本分类、数据清洗怎么选技术方案？

---

## 一、为什么需要结构化输出？

### 1.1 自然语言输出的"原罪"

看看 LLM 自然语言输出的实际下场：

```python
"""自然语言输出的灾难现场"""

def parse_response_to_user(response_text: str) -> dict:
    """试图从 LLM 的自然语言回复中提取结构化信息"""
    # 用户说："我叫张三，今年28岁，住在北京，会Python和Go"
    # LLM 可能会回复：
    responses = [
        "好的！我来整理一下：姓名是张三，年龄28岁，城市北京，技能Python和Go。",
        "根据您提供的信息：\n- 姓名：张三\n- 年龄：28\n- 城市：北京\n- 技能：Python、Go",
        "张三（28岁）来自北京，掌握Python和Go语言。",
        "你好张三！28岁在北京做开发，会Python和Go，真不错！",
        "{'name':'张三','age':28,'city':'北京','skills':['Python','Go']}",
        '{"name": "张三", "age": 28, "city": "北京", "skills": ["Python", "Go"]}',
    ]

    # 看看你前端/后端要怎么解析……
    # 第一种方式：正则匹配？万一语气变了呢？
    # 第二种方式：JSON 解析？可有时候有 MD 代码块，有时候没有
    # 第三种方式：幻想 LLM "每次都输出一样的格式"？
    pass
```

**核心矛盾：LLM 的强项（灵活表达）是你的灾难（无法可靠解析）。**

### 1.2 你真正需要的

| 自然语言输出 | 结构化输出 |
|-------------|-----------|
| LLM 想说啥说啥 | LLM 必须按 Schema 输出 |
| 解析靠玄学 + 正则 | 解析靠 `json.loads()` 一次搞定 |
| 字段缺失要靠 LLM 重新生成 | Schema 约定 required |
| 类型全靠猜（"28"是 int 还是 str？） | 类型严格约定（int / str / list） |
| 四个 LLM 回复风格完全不同 | 四个 LLM 回复 JSON 结构完全一致 |
| **Debug 地狱** | **可测试、可断言** |

### 1.3 真实场景：没有结构化输出会怎样

```python
"""一个真实的信息提取管线 — 没有结构化的版本"""

def extract_info_rag(raw_text: str) -> dict:
    """假设你在做一个简历解析系统"""
    # 步骤 1：把简历发给 LLM 要求总结
    prompt = f"从以下文本中提取姓名、年龄、技能：\n{raw_text}"
    # 调用 LLM…
    response = llm_response  # 谁知道 LLM 回了什么格式？

    # 步骤 2：试图用正则解析
    import re
    name_match = re.search(r"姓名[：:]\s*(\S+)", response)
    # 万一 LLM 回的是："我找到了，名字是张三" ？正则就挂了
    # 万一 LLM 回的是 Markdown 表格？又挂了
    # 万一 LLM 直接给了 JSON 但没有姓名键？又有分支

    # 结论：没有结构化输出，下游代码永远在"猜"
    return {"name": "unknown", "age": 0, "skills": []}
```

> **💡 一句话总结：结构化输出 = LLM 说程序能直接用的语言。没有它，你的代码永远是"猜 LLM 在想什么"。**

---

## 二、四种方式对比表

| 方式 | 原理 | 可靠性 | 复杂度 | 支持度 | 适用场景 |
|------|------|--------|--------|--------|---------|
| **① Prompt 指令法** | 在 system prompt 里写"请输出 JSON" | ⭐⭐ | 最低 | 所有 LLM | 快速原型、非关键场景 |
| **② JSON Mode** | API 参数 `response_format={"type":"json_object"}` | ⭐⭐⭐ | 低 | OpenAI、DeepSeek、ollama 等 | 信息提取、简单分类 |
| **③ Function Calling** | 定义一个有参数的 tool，LLM 通过 tool_calls 输出 | ⭐⭐⭐⭐ | 中 | OpenAI、Claude、DeepSeek、通义 | 工具调用+结构输出混合场景 |
| **④ Constrained Decoding** | 解码阶段强制 token 走合法路径 | ⭐⭐⭐⭐⭐ | 高 | ollama + `grammar`、`lm-format-enforcer` | 生产级、对格式零容忍 |

### 2.1 Prompt 指令法（最原始）

```python
"""方式一：就靠提示词"""

prompt = """请从以下文本中提取信息，以 JSON 格式返回，不要任何其他文字。
字段：name(string), age(int), city(string), skills(list[string])

文本：我叫李四，今年35岁，深圳人，会Java、Kubernetes和Docker。

JSON:"""

# 问题：LLM 可能加 ```json 代码块、可能加注释、可能多写"好的"
# 你说"不要任何其他文字"——但 LLM 经常不听话
```

**踩坑记录 #1：永远不要相信 LLM 会乖乖只输出 JSON。** 哪怕你写"只输出 JSON，不要其他文字"，它也可能在前面加个"好的"或者"这是你需要的JSON："。你永远要在外面包一层正则剥离逻辑。

### 2.2 JSON Mode（今天的主角）

```python
"""方式二：API 级 JSON Mode——LLM 知道必须输出 JSON"""

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[...],
    response_format={"type": "json_object"},  # 👈 就这一行
)

# 效果：LLM 绝对不会输出纯文本，永远是 JSON
# 代价：你必须在 prompt 中告诉它 JSON 的 schema（不然它瞎生成）
```

### 2.3 Function Calling 做结构输出

```python
"""方式三：Function Calling 当结构输出用"""

# 定义一个"提取信息"的 tool，但根本不执行它
tools = [{
    "type": "function",
    "function": {
        "name": "extract_info",
        "description": "从文本中提取结构化信息",
        "parameters": {  # 这个 schema 就是你的输出约束
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
                "city": {"type": "string"},
            },
            "required": ["name", "age", "city"],
        },
    },
}]

# LLM 回复的不是自然语言，而是 tool_calls 中的 arguments
```

### 2.4 Constrained Decoding

```python
"""方式四：Constrained Decoding——最铁但最麻烦"""

# 给个概念：配合 ollama + GBNF grammar
# grammar 定义：
# root ::= "{" ws "name" ws ":" ws string ws "}"
# string ::= "\"" [^"]* "\""
# ws ::= " "?

# ollama run llama3 "..." --grammar extract.gbnf
# 效果：解码阶段就约束 token，LLM 想输出非法字符？不可能。
# 代价：需要本地/自建推理，云端 API 基本不支持。
```

---

## 三、JSON Mode 实战：信息提取

### 3.1 最简可运行版本

```python
"""json_mode_demo.py — 完整可运行"""

import json
import os
from openai import OpenAI

# ── 配置（从环境变量读取 API Key） ──────────────────────
client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY", "sk-your-key-here"),
    base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
)


def extract_info_structured(text: str) -> dict:
    """使用 JSON Mode 从自然语言中提取结构化信息"""
    response = client.chat.completions.create(
        model="gpt-4o-mini",  # 便宜够用
        messages=[
            {
                "role": "system",
                "content": """你是一个信息提取助手。从用户提供的文本中提取以下字段，
以 JSON 格式返回（不要代码块、不要额外文字）。

字段说明：
- name: 姓名（string）
- age: 年龄（integer，如果没提到就填 null）
- city: 城市（string，如果没提到就填 null）
- skills: 技能列表（array of string）
""",
            },
            {"role": "user", "content": text},
        ],
        response_format={"type": "json_object"},  # 🎯 JSON Mode 开关
    )

    raw = response.choices[0].message.content
    # 理论上 JSON Mode 保证返回 JSON，但还是防御一下
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[WARN] JSON 解析失败: {e}")
        print(f"[WARN] 原始响应: {raw}")
        return {}


# ── 测试 ─────────────────────────────────────────
if __name__ == "__main__":
    test_texts = [
        "我叫张三，今年28岁，住在北京，会Python和Go",
        "我是王五，精通Java、Spring Boot和微服务架构",
        "我是Python全栈工程师，会Django、FastAPI和React",
        "Alex, 32, from Shanghai, skilled in Go and Kubernetes",
    ]

    for text in test_texts:
        result = extract_info_structured(text)
        print(f"输入: {text}")
        print(f"输出: {json.dumps(result, ensure_ascii=False, indent=2)}")
        print("-" * 60)
```

**预期输出：**
```json
输入: 我叫张三，今年28岁，住在北京，会Python和Go
输出: {
  "name": "张三",
  "age": 28,
  "city": "北京",
  "skills": ["Python", "Go"]
}
```

> **💡 JSON Mode 的关键**：`response_format={"type": "json_object"}` 告诉 API"只输出 JSON"。但是**LLM 不知道 JSON 里该有啥字段**——你必须在 prompt 里写清楚 schema。这被称为「Prompt Bind」模式——格式由 API 保证，内容由 Prompt 定义。

### 3.2 文本分类实战

```python
"""json_mode_classify.py — 文本分类 + 置信度"""

import json
import os
from openai import OpenAI

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY", "sk-your-key-here"),
    base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
)

# 定义分类体系
CATEGORIES = ["技术", "娱乐", "体育", "财经", "教育", "其他"]

CLASSIFY_PROMPT = f"""你是一个文本分类器。对输入的文本进行分类，以 JSON 格式返回。

分类体系：{', '.join(CATEGORIES)}

返回格式：
{{
    "category": "分类名称",
    "confidence": 0.0~1.0,
    "reason": "简短的分类理由（一句话）"
}}

注意：
- confidence 必须是一个 0 到 1 之间的浮点数
- category 必须在上述分类体系中
- 不要输出代码块，只输出 JSON
"""


def classify_text(text: str) -> dict:
    """对文本进行分类"""
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": CLASSIFY_PROMPT},
            {"role": "user", "content": text},
        ],
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content)


if __name__ == "__main__":
    samples = [
        "OpenAI 发布 GPT-5，性能提升 10 倍",
        "昨晚的足球比赛太精彩了，C罗梅开二度",
        "A股三大指数今日集体上涨，沪指重回3000点",
        "这篇文章讲的是如何使用 Python 做数据分析",
    ]

    for text in samples:
        result = classify_text(text)
        print(f"[{result['category']}] ({result['confidence']:.0%}) {text[:30]}...")
        print(f"  理由: {result['reason']}")
```

**预期输出：**
```
[技术] (95%) OpenAI 发布 GPT-5，性能提升 10 倍...
  理由: 内容涉及 AI 技术发布
[体育] (98%) 昨晚的足球比赛太精彩了，C罗梅开二度...
  理由: 描述足球比赛和运动员表现
[财经] (92%) A股三大指数今日集体上涨，沪指重回3000点...
  理由: 涉及股票市场和指数变化
[教育] (88%) 这篇文章讲的是如何使用 Python 做数据分析...
  理由: 内容涉及 Python 编程教学
```

### 3.3 JSON Mode 的坑

**踩坑记录 #2：JSON Mode 不是 Schema 约束，只是格式约束。**

```python
# JSON Mode 保证的是：LLM 输出是合法 JSON
# 但不保证：JSON 里的字段名、字段类型、必填字段是你想要的

# 你 prompt 里写了要 name/age/city
# LLM 可能输出：
# {"name": "张三", "age": 28, "city": "北京"}  ✅ 完美
# {"full_name": "张三", "years_old": 28}         ❌ 字段名变了！
# {"name": "张三", "age": "二十八", "city": "北京"} ❌ 类型变了！
```

**踩坑记录 #3：prompt 里写 schema，换模型可能不兼容。**
你写 GPT-4o 上精调的 schema 提示词，换到 DeepSeek 或 Claude 上可能 LLM 理解不同，输出字段名不一样。**JSON Mode 强依赖 prompt 质量**。

---

## 四、Pydantic v2 反序列化：把 JSON 变成类型安全的 Python 对象

到现在我们只是拿到了一坨 `dict`。对于生产代码，你需要**类型安全、IDE 提示好、能验证**的 Python 对象。

### 4.1 Pydantic v2 基础

```python
"""pydantic_demo.py — Pydantic v2 反序列化"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional


class PersonInfo(BaseModel):
    """人员信息模型"""
    name: str = Field(description="姓名")
    age: Optional[int] = Field(default=None, description="年龄，整数")
    city: Optional[str] = Field(default=None, description="所在城市")
    skills: list[str] = Field(default_factory=list, description="技能列表")

    @field_validator("age")
    @classmethod
    def age_must_be_reasonable(cls, v):
        if v is not None and (v < 0 or v > 150):
            raise ValueError(f"年龄不合法: {v}")
        return v


class ClassificationResult(BaseModel):
    """分类结果模型"""
    category: str = Field(description="分类名称")
    confidence: float = Field(ge=0.0, le=1.0, description="置信度 0-1")
    reason: str = Field(description="分类理由")


# ── 核心方法：从 JSON 到 Pydantic ─────────────────────

def parse_person(json_str: str) -> PersonInfo:
    """解析 JSON 字符串为 PersonInfo 对象"""
    return PersonInfo.model_validate_json(json_str)


def parse_person_from_dict(data: dict) -> PersonInfo:
    """从 dict 解析"""
    return PersonInfo.model_validate(data)


if __name__ == "__main__":
    # 测试: 完美数据
    json_good = '{"name": "张三", "age": 28, "city": "北京", "skills": ["Python", "Go"]}'
    p = parse_person(json_good)
    print(f"✅ 姓名: {p.name}, 年龄: {p.age}, 城市: {p.city}")
    print(f"   技能: {', '.join(p.skills)}")
    print(f"   类型: {type(p)}")
    print()

    # 测试: 缺失字段
    json_partial = '{"name": "李四"}'
    p2 = parse_person(json_partial)
    print(f"✅ 部分数据: {p2.name}, age={p2.age}, city={p2.city}, skills={p2.skills}")
    print()

    # 测试: 非法年龄
    json_bad_age = '{"name": "王五", "age": 999}'
    try:
        parse_person(json_bad_age)
    except Exception as e:
        print(f"❌ 非法年龄被捕获: {e}")
    print()

    # 测试: 完整管线: JSON Mode → Pydantic
    raw_json = '{"category": "技术", "confidence": 0.95, "reason": "AI发布新闻"}'
    cls = ClassificationResult.model_validate_json(raw_json)
    print(f"✅ 分类: {cls.category} ({cls.confidence:.0%})")
    print(f"   理由: {cls.reason}")
```

**Pydantic v2 关键方法速查：**

| 方法 | 作用 | 相当于 |
|------|------|--------|
| `Model.model_validate(data)` | 从 dict 验证 | `pydantic v1` 的 `.parse_obj()` |
| `Model.model_validate_json(json_str)` | 从 JSON 字符串验证 | `pydantic v1` 的 `.parse_raw()` |
| `Model.model_dump()` | 转回 dict | `pydantic v1` 的 `.dict()` |
| `Model.model_dump_json()` | 转回 JSON 字符串 | `pydantic v1` 的 `.json()` |
| `Model.model_json_schema()` | 生成 JSON Schema | 给 LLM 当 tool schema 用 |
| `model.model_fields` | 获取字段定义（dict） | 自省用 |

### 4.2 用 model_json_schema() 生成 LLM 可读的 Schema

```python
"""schema_gen.py — 让 Pydantic 直接生成 JSON Schema"""

from pydantic import BaseModel, Field
from typing import Optional


class PersonInfo(BaseModel):
    name: str = Field(description="姓名")
    age: Optional[int] = Field(default=None, description="年龄")
    city: Optional[str] = Field(default=None, description="所在城市")
    skills: list[str] = Field(default_factory=list, description="技能列表")


# ── 核心方法：Pydantic → JSON Schema ─────────────────
schema = PersonInfo.model_json_schema()
import json
print(json.dumps(schema, ensure_ascii=False, indent=2))
```

**输出：**
```json
{
  "$defs": {
    "PersonInfo": {
      "properties": {
        "name": { "description": "姓名", "title": "Name", "type": "string" },
        "age": {
          "anyOf": [{"type": "integer"}, {"type": "null"}],
          "default": null,
          "description": "年龄",
          "title": "Age"
        },
        "city": {
          "anyOf": [{"type": "string"}, {"type": "null"}],
          "default": null,
          "description": "所在城市",
          "title": "City"
        },
        "skills": {
          "default": [],
          "description": "技能列表",
          "items": {"type": "string"},
          "title": "Skills",
          "type": "array"
        }
      },
      "required": ["name"],
      "title": "PersonInfo",
      "type": "object"
    }
  }
}
```

> **💡 `model_json_schema()` 的价值**：你只需要维护一份 Pydantic 模型定义，JSON Schema 自动生成。不用担心手写 schema 时字段名拼错、类型不匹配。**单源真理（Single Source of Truth）**。

---

## 五、Function Calling 做结构化输出

### 5.1 用 Pydantic schema 定义 tool

这是生产中最常用的方式——尤其是你已经**有 Agent 循环（Day 03）**的情况下。Function Calling 天然比 JSON Mode 多了几个好处：

```python
"""fc_structured_output.py — Function Calling 做结构输出"""

import json
import os
from openai import OpenAI
from pydantic import BaseModel, Field
from typing import Optional

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY", "sk-your-key-here"),
    base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
)


# ── 1. 用 Pydantic 定义输出结构 ──────────────────────
class ResumeInfo(BaseModel):
    """简历信息"""
    name: str = Field(description="姓名")
    age: Optional[int] = Field(default=None, description="年龄")
    city: Optional[str] = Field(default=None, description="所在城市")
    skills: list[str] = Field(default_factory=list, description="技能列表")
    years_experience: Optional[int] = Field(default=None, description="工作年限")
    education: Optional[str] = Field(default=None, description="最高学历")


# ── 2. 自动生成 Function Calling 的 Tool Schema ────────
def pydantic_to_tool(model: type[BaseModel]) -> dict:
    """将 Pydantic 模型转换为 Function Calling 的 tool schema"""
    # 只取 $defs 中的第一个 schema，去掉外层的 $defs 包装
    schema = model.model_json_schema()
    # 如果 schema 有 $defs，说明有嵌套，取顶层定义
    if "$defs" in schema:
        ref = schema.get("$ref", "")
        def_name = ref.split("/")[-1]
        params = schema["$defs"][def_name]
    else:
        params = schema

    return {
        "type": "function",
        "function": {
            "name": model.__name__.lower(),
            "description": model.__doc__ or "",
            "parameters": params,
        },
    }


# ── 3. 用 Function Calling 提取信息 ────────────────────
def extract_resume(text: str) -> ResumeInfo:
    """通过 Function Calling 提取简历信息"""
    tool = pydantic_to_tool(ResumeInfo)

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": "你是一个简历信息提取助手。请使用 extract_info 工具输出提取结果。",
            },
            {"role": "user", "content": text},
        ],
        tools=[tool],
        tool_choice={
            "type": "function",
            "function": {"name": "resumeinfo"},
        },  # 🎯 强制调这个 tool
    )

    # 从 tool_calls 中提取参数
    msg = response.choices[0].message
    if msg.tool_calls:
        args_str = msg.tool_calls[0].function.arguments
        return ResumeInfo.model_validate_json(args_str)

    raise ValueError("LLM 没有调用 extract_info tool，这不应该发生")


if __name__ == "__main__":
    texts = [
        "我叫张三，28岁，北京人，本科学历，会Python和Go，有5年开发经验",
        "我是王五，硕士学历，精通Java、Spring Boot，在上海工作3年了",
        "Alex, PhD in CS, 8 years of experience in ML and distributed systems, NYC",
    ]

    for text in texts:
        info = extract_resume(text)
        print(f"📄 {info.name} | {info.age}岁 | {info.city}")
        print(f"   学历: {info.education or '未提及'} | 经验: {info.years_experience or '未知'}年")
        print(f"   技能: {', '.join(info.skills)}")
        print()
```

### 5.2 JSON Mode vs Function Calling 做结构输出

| 对比维度 | JSON Mode | Function Calling |
|---------|-----------|-----------------|
| API 参数 | `response_format={"type":"json_object"}` | `tools=[...], tool_choice={"type":"function",...}` |
| 输出位置 | `message.content` | `message.tool_calls[0].function.arguments` |
| Schema 约束 | Prompt 里写，**软约束** | API 级参数，**硬约束** |
| 字段名称稳定性 | LLM 可能改字段名 | 严格按 parameters 定义 |
| 类型约束 | LLM 可能把 int 写成 str | LLM 必须输出合法 JSON 类型 |
| 必填字段 | Prompt 里用文字说"必须" | `parameters.required` 硬约束 |
| 兼容性 | 只有部分 API 支持 | OpenAI 兼容 API 普遍支持 |
| 与其他 tool 混用 | 不行，JSON Mode 独占 | 可以和其他 tool 一起用 |

**踩坑记录 #4：Function Calling 做结构输出，一定要用 `tool_choice` 强制指定。**
如果不指定 `tool_choice`，LLM 可能会返回自然语言而不是调 tool——那就没有结构输出了。

```python
# ✅ 正确：强制使用
tool_choice = {"type": "function", "function": {"name": "resumeinfo"}}

# ❌ 翻车：LLM 可能不回 tool_calls
# 不加 tool_choice → LLM 可能直接说"好的，我来提取"
```

**踩坑记录 #5：`tool_choice: "required"` 有时比指定名称更通用。**

```python
# 如果你有多个 tool，或者不确定 tool 名字：
tool_choice = "required"
# 意思：LLM 必须调至少一个 tool，具体调哪个 LLM 自己选
# 单 tool 场景也适用，且不用写函数名（避免拼写错误）
```

---

## 六、决策树：什么时候用哪种方式

```
                           你的需求
                              │
                    ┌─────────┴──────────┐
                    ▼                    ▼
              需要结构输出          需要工具调用
                    │                    │
         ┌──────────┴──────────┐         │
         ▼                     ▼         │
    API 支持 JSON Mode     API不支持      │
         │                     │         │
    ┌────┴────┐          ┌────┴────┐    │
    ▼         ▼          ▼         ▼    ▼
原型/简单    字段复杂    Function   Prompt
场景        必须匹配    Calling    指令法
            Pydantic   强制指定   (兜底)
                │       tool_
                ▼       choice
           JSON Mode    ────► 结构输出
           + Pydantic
           验证

          需要零容错、格式必须合法？
                │
                ▼
        Constrained Decoding
        (自建推理 / ollama / llama.cpp)
```

### 6.1 实战选择建议

| 你的场景 | 推荐方案 | 理由 |
|---------|---------|------|
| 快速原型、内部工具 | JSON Mode | 一行参数，零配置 |
| 信息提取（简历/文档解析） | JSON Mode + Pydantic | 够用，简单 |
| 已经用了 Agent Loop 和 Function Calling | Function Calling 做输出 | 复用已有机制 |
| 文本分类/情感分析 | JSON Mode | 天生适合，不需要 tool |
| 多步 Agent（搜索→提取→总结） | Function Calling | Agent Loop 自然结合 |
| 生产级、字段必须正确 | Function Calling + Pydantic 验证 | 双重保证 |
| 格式零容忍、自建推理 | Constrained Decoding | 不存在格式错误 |
| 一次性脚本、快速调试 | Prompt 指令法 | 零依赖 |

---

## 七、动手实验

### 实验 1：对比四种方式

```python
"""experiment_compare.py — 对比四种结构化输出方式"""

import json
import os
import time
from openai import OpenAI

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY", "sk-your-key-here"),
    base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
)

TEXT = "我叫赵六，今年32岁，在杭州从事数据分析工作，精通Python、SQL和Tableau"

# ── 方式 1: Prompt 指令法 ─────────────────────────
print("=" * 60)
print("方式 1: Prompt 指令法")
start = time.time()

resp1 = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[
        {"role": "system", "content": "只输出 JSON，不要其他文字。格式：{\"name\":\"\", \"age\":0, \"city\":\"\"}"},
        {"role": "user", "content": TEXT},
    ],
)
t1 = time.time() - start
raw1 = resp1.choices[0].message.content
print(f"耗时: {t1:.2f}s")
print(f"原始输出: {raw1}")
try:
    # 尝试清理可能的前后多余文字
    cleaned = raw1.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    print(f"解析结果: {json.loads(cleaned)}")
except Exception as e:
    print(f"❌ 解析失败: {e}")
print()

# ── 方式 2: JSON Mode ─────────────────────────────
print("方式 2: JSON Mode")
start = time.time()

resp2 = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[
        {"role": "system", "content": "提取信息并返回 JSON：name(string), age(int), city(string), skills(list[string])"},
        {"role": "user", "content": TEXT},
    ],
    response_format={"type": "json_object"},
)
t2 = time.time() - start
raw2 = resp2.choices[0].message.content
print(f"耗时: {t2:.2f}s")
print(f"原始输出: {raw2}")
print(f"解析结果: {json.loads(raw2)}")
print()

# ── 方式 3: Function Calling ──────────────────────
print("方式 3: Function Calling")
start = time.time()

resp3 = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[
        {"role": "system", "content": "提取信息，使用 extract_info tool 输出"},
        {"role": "user", "content": TEXT},
    ],
    tools=[{
        "type": "function",
        "function": {
            "name": "extract_info",
            "description": "提取结构化信息",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "age": {"type": "integer"},
                    "city": {"type": "string"},
                    "skills": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name"],
            },
        },
    }],
    tool_choice={"type": "function", "function": {"name": "extract_info"}},
)
t3 = time.time() - start
raw3 = resp3.choices[0].message.tool_calls[0].function.arguments
print(f"耗时: {t3:.2f}s")
print(f"原始输出: {raw3}")
print(f"解析结果: {json.loads(raw3)}")
print()

# ── 总结 ──────────────────────────────────────────
print("=" * 60)
print("对比总结：")
print(f"  Prompt 指令法:  {t1:.2f}s — 可靠性最低，需要额外清洗")
print(f"  JSON Mode:      {t2:.2f}s — 稳妥，一行参数")
print(f"  Function Call:  {t3:.2f}s — 最可靠，参数结构严格")
```

### 实验 2：批量信息提取 + Pydantic 验证管线

```python
"""experiment_pipeline.py — 完整的信息提取管线"""

import json
import os
from openai import OpenAI
from pydantic import BaseModel, Field, field_validator
from typing import Optional

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY", "sk-your-key-here"),
    base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
)


class PersonInfo(BaseModel):
    name: str = Field(description="姓名")
    age: Optional[int] = Field(default=None, description="年龄")
    city: Optional[str] = Field(default=None, description="所在城市")
    skills: list[str] = Field(default_factory=list, description="技能列表")

    @field_validator("age")
    @classmethod
    def check_age(cls, v):
        if v is not None and v < 0:
            raise ValueError("年龄不能为负数")
        return v


def extract_person_info(text: str) -> PersonInfo:
    """完整的信息提取管线：JSON Mode + Pydantic 验证"""
    # Step 1: 调用 LLM 获取 JSON
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": "你是一个信息提取助手。从文本中提取人员信息，以 JSON 格式返回。"
                           "字段: name(string), age(int|null), city(string|null), skills(list[string])",
            },
            {"role": "user", "content": text},
        ],
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content

    # Step 2: 反序列化
    data = json.loads(raw)

    # Step 3: Pydantic 验证 + 类型转换
    # 这里 age 可能是 string，Pydantic 默认不会自动转
    if "age" in data and isinstance(data.get("age"), str):
        try:
            data["age"] = int(data["age"])
        except (ValueError, TypeError):
            data["age"] = None

    return PersonInfo.model_validate(data)


# ── 批量处理 ──────────────────────────────────────
if __name__ == "__main__":
    raw_texts = [
        "我是小明，今年25岁，在上海做前端开发，会Vue和React",
        "李华，北京，Python后端，5年经验",
        "Elon, 52, from Austin, Tesla SpaceX",
        "刚才有个陌生人没留名字说了一堆话，年龄城市都没有",
    ]

    for i, text in enumerate(raw_texts, 1):
        print(f"[{i}] 输入: {text[:40]}...")
        try:
            info = extract_person_info(text)
            print(f"    ✅ {info.name or '(未提取到)'} | {info.age or '?'}岁 | {info.city or '?'}")
            print(f"       技能: {', '.join(info.skills) if info.skills else '无'}")
        except Exception as e:
            print(f"    ❌ 错误: {e}")
        print()
```

### 实验 3：自己动手做

请尝试完成以下练习：

**练习 1：商品信息提取**
从一段商品描述文本中提取：商品名、价格（float）、品牌、规格尺寸、颜色列表。用 Pydantic 定义模型，用 JSON Mode 提取。

**练习 2：情感分析 + 关键词抽取**
给定一段评论，输出：
- `sentiment`: "positive"/"negative"/"neutral"
- `score`: 0.0~1.0
- `keywords`: list[string]
- `summary`: string（一句话概括）

**练习 3：对比实验**
对同一段文本，分别用 JSON Mode 和 Function Calling 提取 10 次，统计字段缺失率、类型错误率、平均耗时。你可能会发现一些有趣的差异。

---

## 八、踩坑记录总汇

| # | 坑 | 现象 | 解决方案 |
|---|-----|------|---------|
| 1 | Prompt 指令法不听话 | LLM 加额外文字、代码块 | 防御性清理 + 降级到 JSON Mode |
| 2 | JSON Mode 只保格式不保内容 | 字段名变了、类型错了 | 加 Pydantic 验证兜底 |
| 3 | 换模型兼容性问题 | prompt 里的 schema 在新模型上失效 | 用 Function Calling（API 级约束） |
| 4 | FC 忘记 tool_choice | LLM 直接回了文字，没有结构 | 总是加上 `tool_choice` 或 `tool_choice="required"` |
| 5 | Pydantic `model_validate` 不自动转类型 | LLM 输出 `age: "28"` 但 Pydantic 期望 int | 手动 `int()` 转一层，或用 Pydantic 的 `coerce_numbers_to_str` |
| 6 | LLM 输出编码问题 | 中文被转义为 `\u5f20\u4e09` | `json.loads()` 默认能处理，或 `ensure_ascii=False` 重新 dump |
| 7 | 多层嵌套时 schema 复杂 | Pydantic 生成 $defs 嵌套，Function Calling 报错 | 扁平化模型，或者手写平铺 JSON Schema |

### Pydantic 验证兜底模式（推荐）

```python
"""最终的防御性模式"""

import json
from pydantic import BaseModel, ValidationError


def safe_parse(model_class: type[BaseModel], raw_json: str) -> BaseModel | None:
    """安全解析：JSON 解析 + Pydantic 验证，失败返回 None"""
    try:
        data = json.loads(raw_json)
        return model_class.model_validate(data)
    except (json.JSONDecodeError, ValidationError) as e:
        print(f"[ERROR] 解析失败: {e}")
        print(f"[ERROR] 原始数据: {raw_json[:200]}")
        return None
```

---

## 副线笔记

### 什么是 JSON Schema？

JSON Schema 是一种声明式的数据格式描述语言。你在本教程中一直在用但可能没意识到：
- `{"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}`
- 这就是 JSON Schema。所有 LLM 的 `tools` 参数、Pydantic 的 `model_json_schema()` 输出都是 JSON Schema。

在线 JSON Schema 验证器：https://www.jsonschemavalidator.net/

### Structured Output vs JSON Mode

OpenAI 2024 年 8 月推出了「Structured Outputs」——这是 JSON Mode 的升级版。区别：
- JSON Mode（老）：`response_format={"type": "json_object"}`
- Structured Outputs（新）：`response_format={"type": "json_schema", "json_schema": {...}}`

**Structured Outputs 可以直接传 JSON Schema，不需要在 prompt 里写字段名**。比 JSON Mode 更可靠。但不是所有 API 提供商都支持。如果你用的是最新版 OpenAI，优先用 Structured Outputs。

```python
# OpenAI Structured Outputs（2024+）
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[...],
    response_format={
        "type": "json_schema",
        "json_schema": {
            "name": "person_info",
            "schema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "age": {"type": "integer"},
                },
                "required": ["name"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    },
)
```

### 关于 JSON Mode 的成本

JSON Mode 和 Function Calling 基本没有额外 token 开销——开销主要来自 schema 定义本身。但在某些 API 上，`tools` 参数会占用较多的**上下文 token**（因为它每次请求都要传）。所以：
- 如果只是简单的信息提取 → JSON Mode 更省 token（tools 参数通常比 prompt 里的 schema 描述更长）
- 如果已经在用 Agent Loop → Function Calling 顺手，多带一个 tool 开销很小

### 关于 constrained decoding 的实战意义

如果你用 ollama / llama.cpp / vLLM 自建推理，Constrained Decoding 是最优解——它**不可能产出格式错误的 JSON**。代价是：
1. 增加了推理延迟（每一步都要检查 token 是否合法）
2. 实现复杂（需要 GBNF grammar 或 lm-format-enforcer）
3. 不适合快速原型开发

但在生产环境，如果格式错误会导致下游系统崩溃（比如金额解析、合同条款提取），Constrained Decoding 值得投资。

---

## 今日总结

```
Day 04 核心收获
├── 结构化输出 = 让 LLM 说机器能直接用的语言
├── 四种方式
│   ├── ① Prompt 指令法：不靠谱但零门槛
│   ├── ② JSON Mode：一行参数，够用
│   ├── ③ Function Calling：最可靠，与 Agent Loop 天然集成
│   └── ④ Constrained Decoding：零容错但实现复杂
├── Pydantic v2 三件套
│   ├── BaseModel + Field 定义模型
│   ├── model_validate_json() 反序列化
│   └── model_json_schema() 生成 Schema
├── 生产推荐：JSON Mode / FC + Pydantic 验证 = 双层保证
└── 明天预告：Day 05 —— 记忆 Management（Memory）
    ── Agent 怎么记住对话历史，怎么做长对话管理
```

**明天见！** 🚀
