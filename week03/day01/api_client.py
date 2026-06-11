"""
API 客户端 —— Day 01 教程示例
================================

使用 httpx 直接调用 LLM API（不依赖 OpenAI SDK），演示：
  1. call_llm()         —— OpenAI 兼容格式（流式 / 非流式）
  2. call_llm_anthropic() —— Anthropic 格式对比
  3. call_llm_stream()     —— 流式逐块打印
  4. extract_usage()       —— 提取 Token 用量

安装依赖: pip install httpx
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

import httpx

# ──────────────────────────────────────────────
#  全局配置
# ──────────────────────────────────────────────

# OpenAI 兼容端点（默认为 DeepSeek 公开 API）
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com/v1")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# Anthropic 端点
ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# 默认模型
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "deepseek-chat")


# ══════════════════════════════════════════════
#  1. call_llm —— OpenAI 兼容格式
# ══════════════════════════════════════════════

def call_llm(
    messages: list[dict[str, str]],
    model: str = DEFAULT_MODEL,
    temperature: float = 0.7,
    max_tokens: int = 1024,
    stream: bool = False,
    base_url: str | None = None,
    api_key: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    调用 OpenAI 兼容的 LLM API，返回完整响应字典。

    参数
    ----
    messages : list[dict]
        对话消息，格式为 [{"role": "user", "content": "你好"}]
    model : str
        模型名称
    temperature : float
        采样温度 (0 ~ 2)
    max_tokens : int
        最大生成 token 数
    stream : bool
        是否启用流式 —— 本函数非流式返回；如需流式请用 call_llm_stream()
    base_url : str | None
        自定义 API 基地址，默认使用 OPENAI_BASE_URL
    api_key : str | None
        自定义 API Key，默认使用 OPENAI_API_KEY
    **kwargs :
        透传给请求体的额外参数（top_p, stop 等）

    返回
    ----
    dict
        完整 HTTP 响应 JSON（包含 choices, usage 等字段）
    """
    url = f"{(base_url or OPENAI_BASE_URL).rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key or OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": stream,
        **kwargs,
    }

    with httpx.Client(timeout=60.0) as client:
        resp = client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        return resp.json()


# ══════════════════════════════════════════════
#  2. call_llm_anthropic —— Anthropic 格式
# ══════════════════════════════════════════════

def call_llm_anthropic(
    messages: list[dict[str, str]],
    model: str = "claude-sonnet-4-20250514",
    max_tokens: int = 1024,
    temperature: float = 0.7,
    base_url: str | None = None,
    api_key: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    调用 Anthropic Messages API，对比与 OpenAI 格式的差异。

    主要区别：
      - Anthropic 使用 "messages" 顶层字段传递对话
      - 显式声明 "max_tokens"（必填），且与 OpenAI 命名一致
      - 响应中 content 是列表，每项有 type + text
      - stop_reason 是 "end_turn" / "max_tokens" 而非 "stop" / "length"
      - Token 用量在 usage.input_tokens / usage.output_tokens

    参数
    ----
    与 call_llm 类似，但 model 和 max_tokens 含义略有不同
    """
    url = f"{(base_url or ANTHROPIC_BASE_URL).rstrip('/')}/messages"
    headers = {
        "x-api-key": api_key or ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        **kwargs,
    }

    with httpx.Client(timeout=60.0) as client:
        resp = client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        return resp.json()


# ══════════════════════════════════════════════
#  3. call_llm_stream —— 流式调用
# ══════════════════════════════════════════════

def call_llm_stream(
    messages: list[dict[str, str]],
    model: str = DEFAULT_MODEL,
    temperature: float = 0.7,
    max_tokens: int = 1024,
    base_url: str | None = None,
    api_key: str | None = None,
    **kwargs: Any,
) -> str:
    """
    流式调用 OpenAI 兼容 API，边收边打印，返回完整拼接文本。

    流程：
      1. 设置 stream=True 发送请求
      2. 按行读取 SSE 事件（data: {...}）
      3. 遇到 [DONE] 结束
      4. 实时打印增量内容
      5. 返回最终拼接文本

    返回
    ----
    str
        模型生成的完整文本内容
    """
    url = f"{(base_url or OPENAI_BASE_URL).rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key or OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
        **kwargs,
    }

    full_text = ""
    print("=" * 60)
    print("【流式响应开始】")
    print("=" * 60)

    with httpx.Client(timeout=120.0) as client:
        with client.stream("POST", url, headers=headers, json=payload) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line.removeprefix("data: ").strip()
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                # 取出增量文本
                delta = (
                    chunk.get("choices", [{}])[0]
                    .get("delta", {})
                    .get("content", "")
                )
                if delta:
                    print(delta, end="", flush=True)
                    full_text += delta

    print()  # 换行
    print("=" * 60)
    print("【流式响应结束】")
    print("=" * 60)
    return full_text


# ══════════════════════════════════════════════
#  4. extract_usage —— 提取 Token 用量
# ══════════════════════════════════════════════

def extract_usage(response: dict[str, Any]) -> dict[str, int]:
    """
    从 LLM 响应中提取 Token 用量信息。

    兼容 OpenAI 和 Anthropic 两种格式：

    OpenAI 格式:
        response["usage"] = {
            "prompt_tokens": 20,
            "completion_tokens": 50,
            "total_tokens": 70
        }

    Anthropic 格式:
        response["usage"] = {
            "input_tokens": 20,
            "output_tokens": 50
        }

    参数
    ----
    response : dict
        call_llm() 或 call_llm_anthropic() 的返回值

    返回
    ----
    dict
        统一为 {"input": int, "output": int, "total": int} 格式
    """
    usage = response.get("usage", {})
    if not usage:
        return {"input": 0, "output": 0, "total": 0}

    # OpenAI 风格
    if "prompt_tokens" in usage:
        return {
            "input": usage["prompt_tokens"],
            "output": usage["completion_tokens"],
            "total": usage["total_tokens"],
        }

    # Anthropic 风格
    if "input_tokens" in usage:
        total = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
        return {
            "input": usage["input_tokens"],
            "output": usage["output_tokens"],
            "total": total,
        }

    # 兜底：尝试常见字段名
    return {
        "input": usage.get("input_tokens", usage.get("prompt_tokens", 0)),
        "output": usage.get("output_tokens", usage.get("completion_tokens", 0)),
        "total": usage.get("total_tokens", 0),
    }


# ══════════════════════════════════════════════
#  演示入口
# ══════════════════════════════════════════════

if __name__ == "__main__":
    test_messages = [
        {"role": "system", "content": "你是 DeepSeek，请简洁回答。"},
        {"role": "user", "content": "用一句话介绍 httpx 库。"},
    ]

    # ── 演示 1: 非流式调用 ──
    print("\n" + "█" * 60)
    print("█  演示 1: call_llm() —— 非流式调用")
    print("█" * 60)
    if not OPENAI_API_KEY:
        print("⚠  未设置 OPENAI_API_KEY，跳过演示 1")
    else:
        try:
            resp = call_llm(test_messages)
            print("完整响应:", json.dumps(resp, ensure_ascii=False, indent=2)[:800])
            usage = extract_usage(resp)
            print("Token 用量:", usage)
        except Exception as e:
            print(f"✗ 调用失败: {e}")

    # ── 演示 2: Anthropic 调用 ──
    print("\n" + "█" * 60)
    print("█  演示 2: call_llm_anthropic() —— Anthropic 格式调用")
    print("█" * 60)
    if not ANTHROPIC_API_KEY:
        print("⚠  未设置 ANTHROPIC_API_KEY，跳过演示 2")
    else:
        try:
            resp = call_llm_anthropic(test_messages)
            print("Anthropic 响应:", json.dumps(resp, ensure_ascii=False, indent=2)[:800])
            usage = extract_usage(resp)
            print("Token 用量:", usage)
        except Exception as e:
            print(f"✗ 调用失败: {e}")

    # ── 演示 3: 流式调用 ──
    print("\n" + "█" * 60)
    print("█  演示 3: call_llm_stream() —— 流式调用")
    print("█" * 60)
    if not OPENAI_API_KEY:
        print("⚠  未设置 OPENAI_API_KEY，跳过演示 3")
    else:
        try:
            full = call_llm_stream(test_messages)
            print(f"\n完整内容 ({len(full)} 字符): {full}")
        except Exception as e:
            print(f"✗ 流式调用失败: {e}")

    # ── 演示 4: extract_usage 单元测试 ──
    print("\n" + "█" * 60)
    print("█  演示 4: extract_usage() —— Token 用量提取")
    print("█" * 60)

    # OpenAI 格式
    openai_usage = {
        "id": "chatcmpl-xxx",
        "choices": [{"message": {"content": "hello"}}],
        "usage": {"prompt_tokens": 20, "completion_tokens": 50, "total_tokens": 70},
    }
    print("OpenAI 格式 →", extract_usage(openai_usage))

    # Anthropic 格式
    anthropic_usage = {
        "id": "msg_xxx",
        "content": [{"type": "text", "text": "hello"}],
        "usage": {"input_tokens": 20, "output_tokens": 50},
    }
    print("Anthropic 格式 →", extract_usage(anthropic_usage))

    # 空格式
    empty = {"id": "none"}
    print("空响应 →", extract_usage(empty))

    print("\n✓ 所有演示完成")
