"""
结构化输出演示 — JSON Mode vs Function Calling
================================================
对比两种让 LLM 返回结构化数据的方式：
  1. JSON Mode (response_format={'type':'json_object'})
  2. Function Calling (tools + tool_choice)

依赖: pip install httpx pydantic
模拟模式: 未设置 OPENAI_API_KEY 时自动使用内置模拟数据，无 API key 也能跑。
"""

import json
import os
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ── 1. Pydantic 模型定义 ──────────────────────────────────────────────

class ExtractedInfo(BaseModel):
    """从自然语言中提取的个人信息"""
    姓名: str = Field(..., description="人物的中文全名", min_length=1, max_length=20)
    年龄: int = Field(..., description="年龄（周岁）", ge=0, le=150)
    城市: str = Field(..., description="所在城市", min_length=1)
    技能: list[str] = Field(default_factory=list, description="掌握的技能列表, 每项不超过20字")

    @field_validator("年龄")
    @classmethod
    def 年龄必须合理(cls, v: int) -> int:
        if v < 0 or v > 150:
            raise ValueError(f"年龄 {v} 超出合理范围 (0-150)")
        return v

    @field_validator("技能")
    @classmethod
    def 技能不能为空列表元素(cls, v: list[str]) -> list[str]:
        for s in v:
            if len(s.strip()) == 0:
                raise ValueError("技能列表不能包含空字符串")
        return v


class Classification(BaseModel):
    """文本分类结果"""
    类别: str = Field(
        ...,
        description="文本所属类别",
        pattern=r"^(科技|体育|娱乐|政治|教育|财经|健康|其他)$",
    )
    置信度: float = Field(
        ..., description="分类置信度 (0-1)", ge=0.0, le=1.0
    )
    理由: str = Field(
        ..., description="分类理由简述", max_length=200
    )

    @field_validator("类别")
    @classmethod
    def 类别必须在列表中(cls, v: str) -> str:
        valid = {"科技", "体育", "娱乐", "政治", "教育", "财经", "健康", "其他"}
        if v not in valid:
            raise ValueError(f"类别 '{v}' 不在允许集合 {valid} 中")
        return v


# ── 2. OpenAI API 辅助 ────────────────────────────────────────────────

_API_KEY = os.getenv("OPENAI_API_KEY")
_SIMULATE = _API_KEY is None
_BASE_URL = "https://api.openai.com/v1"

if _SIMULATE:
    print("⚠  未设置 OPENAI_API_KEY，将使用模拟模式（无真实 API 调用）\n")


def _chat_completion(
    messages: list[dict],
    *,
    response_format: Optional[dict] = None,
    tools: Optional[list[dict]] = None,
    tool_choice: Optional[str] = None,
) -> dict:
    """底层调用 OpenAI Chat Completions API (或模拟)。"""
    if _SIMULATE:
        # ── 模拟返回，不发起真实网络请求 ──
        return _simulate_response(messages, response_format, tools, tool_choice)

    body = {
        "model": "gpt-4o",
        "messages": messages,
        "temperature": 0.0,
    }
    if response_format:
        body["response_format"] = response_format
    if tools:
        body["tools"] = tools
    if tool_choice:
        body["tool_choice"] = tool_choice

    import httpx
    resp = httpx.post(
        f"{_BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {_API_KEY}",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


# ── 3. JSON Mode 实现 ─────────────────────────────────────────────────

def call_json_mode(system: str, user: str) -> str:
    """
    使用 response_format={'type': 'json_object'} 强制 LLM 输出 JSON。

    特点：
    - 不需要预定义 tool schema
    - LLM 自动推断 JSON 结构
    - 适合简单/灵活的结构
    - 如果 system 消息不包含 'json' 提示可能不稳定
    """
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    result = _chat_completion(messages, response_format={"type": "json_object"})
    raw = result["choices"][0]["message"]["content"]
    return raw


# ── 4. Function Calling 实现 ──────────────────────────────────────────

def call_function_calling(
    system: str,
    user: str,
    pydantic_model: type[BaseModel],
) -> dict:
    """
    使用 Function Calling（tools + tool_choice）让 LLM 输出结构化数据。

    特点：
    - 通过 Pydantic.model_json_schema() 精确控制输出 schema
    - LLM 只能按 schema 字段输出
    - 支持嵌套、枚举、校验规则
    - 适合复杂/严格的业务场景
    """
    schema = pydantic_model.model_json_schema()

    tools = [
        {
            "type": "function",
            "function": {
                "name": "output_structured",
                "description": f"输出符合 {pydantic_model.__name__} 模型的结构化数据",
                "parameters": schema,
            },
        }
    ]

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    result = _chat_completion(
        messages,
        tools=tools,
        tool_choice={"type": "function", "function": {"name": "output_structured"}},
    )

    # 解析 tool call 参数
    msg = result["choices"][0]["message"]
    if msg.get("tool_calls"):
        args_str = msg["tool_calls"][0]["function"]["arguments"]
        return json.loads(args_str)

    # 回退：可能是文本回复（模拟模式用）
    fallback = json.loads(msg["content"])
    return fallback


# ── 5. 高层封装 ───────────────────────────────────────────────────────

def extract_info(text: str) -> ExtractedInfo:
    """
    从自然语言文本中提取 姓名/年龄/城市/技能。

    同时演示 JSON Mode 和 Function Calling 两种方式，并对比结果。
    """
    system = "你是一个信息提取助手。请从用户输入中提取个人信息并返回 JSON。"

    print(f"{'='*60}")
    print(f"📥 输入文本: {text}")
    print(f"{'='*60}")

    # ── 方式 A: JSON Mode ──
    print("\n── [方式 A] JSON Mode ──")
    raw_json = call_json_mode(system, text)
    data_a = json.loads(raw_json)
    info_a = ExtractedInfo(**data_a)
    print(f"  ✅ 解析成功: {info_a.model_dump_json(indent=2, ensure_ascii=False)}")

    # ── 方式 B: Function Calling ──
    print("\n── [方式 B] Function Calling ──")
    data_b = call_function_calling(system, text, ExtractedInfo)
    info_b = ExtractedInfo(**data_b)
    print(f"  ✅ 解析成功: {info_b.model_dump_json(indent=2, ensure_ascii=False)}")

    # ── 对比 ──
    print(f"\n── 对比 ──")
    print(f"  字段一致: {data_a == data_b}")
    for key in ExtractedInfo.model_fields:
        va = data_a.get(key)
        vb = data_b.get(key)
        print(f"  {key}: JSON Mode={va!r}  vs  FC={vb!r}  {'✓' if va == vb else '✗'}")

    print()
    return info_a  # 默认返回 JSON Mode 的结果


def classify_text(text: str) -> Classification:
    """
    对一段文本进行分类（科技/体育/娱乐/政治/教育/财经/健康/其他）。

    演示 Function Calling 方式和 Pydantic 校验。
    """
    categories = ["科技", "体育", "娱乐", "政治", "教育", "财经", "健康", "其他"]
    system = (
        "你是一个文本分类助手。"
        f"请将文本分类到以下类别之一：{'/'.join(categories)}。"
        "使用 output_structured 工具输出结果。"
    )

    print(f"{'='*60}")
    print(f"📥 待分类文本: {text}")
    print(f"{'='*60}")

    data = call_function_calling(system, text, Classification)
    clf = Classification(**data)
    print(f"  ✅ 分类结果: 类别={clf.类别}, 置信度={clf.置信度}, 理由={clf.理由}")
    print()
    return clf


# ── 6. 模拟数据生成器（无 API key 时使用）──────────────────────────────

_MOCK_COUNTER = 0


def _simulate_response(
    messages: list[dict],
    response_format: Optional[dict] = None,
    tools: Optional[list[dict]] = None,
    tool_choice: Optional[str] = None,
) -> dict:
    """模拟 OpenAI 响应，不用真实 API key。"""
    global _MOCK_COUNTER
    _MOCK_COUNTER += 1

    user_msg = messages[-1]["content"] if messages else ""

    # ── 信息提取模拟 — 匹配任何人名/年龄相关的输入 ──
    if "张三" in user_msg or "岁" in user_msg or "叫" in user_msg:
        content = json.dumps(
            {
                "姓名": "张三",
                "年龄": 28,
                "城市": "北京",
                "技能": ["Python", "数据分析", "机器学习"],
            },
            ensure_ascii=False,
        )
    # ── 分类模拟 ──
    elif "分类" in user_msg or "类别" in user_msg or "类" in user_msg or "OpenAI" in user_msg:
        content = json.dumps(
            {
                "类别": "科技",
                "置信度": 0.95,
                "理由": "文本涉及人工智能和大模型技术，属于科技领域。",
            },
            ensure_ascii=False,
        )
    else:
        content = json.dumps({"message": "模拟响应"}, ensure_ascii=False)

    # ── 如果是 function calling 模式，返回 tool_calls ──
    if tools:
        return {
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": f"call_mock_{_MOCK_COUNTER}",
                                "type": "function",
                                "function": {
                                    "name": "output_structured",
                                    "arguments": content,
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        }

    # ── JSON Mode ──
    return {
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
    }


# ── 7. 演示入口 ──────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  结构化输出演示 — JSON Mode vs Function Calling")
    print("=" * 60)

    # ── 演示 1: 信息提取 ──
    print("\n" + "█" * 60)
    print("█  演示 1：信息提取")
    print("█" * 60)
    extract_info("我叫张三，今年28岁，住在北京。我会Python、数据分析和机器学习。")

    # ── 演示 2: 文本分类 ──
    print("█" * 60)
    print("█  演示 2：文本分类")
    print("█" * 60)
    classify_text(
        "OpenAI 最新发布的大模型在多项基准测试中超越了前代版本，"
        "推理能力提升了 40%。"
    )

    # ── 对比总结 ──
    print("█" * 60)
    print("█  对比总结")
    print("█" * 60)
    print("""
┌──────────────────────┬──────────────────────────────┬──────────────────────────────┐
│      对比维度        │         JSON Mode            │      Function Calling        │
├──────────────────────┼──────────────────────────────┼──────────────────────────────┤
│ 控制精度             │ 弱 — LLM 自由决定 key 名     │ 强 — 由 Pydantic schema 约束  │
│ 字段校验             │ 需后处理校验                  │ 自动继承 Pydantic Field 规则   │
│ 嵌套结构             │ 不稳定                        │ 稳定                         │
│ 模拟/简单场景        │ 推荐                          │ 稍重                         │
│ 生产/复杂场景        │ 不推荐                        │ 推荐                         │
│ API 兼容性           │ 需支持 response_format        │ 更广泛 (tools 字段)           │
│ 输出可解释性         │ LLM 自述可能偏移              │ tool_call 明确对应 schema     │
└──────────────────────┴──────────────────────────────┴──────────────────────────────┘
    """.rstrip())

    print("✅ 演示完成！若要使用真实 API，请设置环境变量 OPENAI_API_KEY。")
