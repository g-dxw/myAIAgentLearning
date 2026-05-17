'''
今日练习（约 2 小时）
#	练习	时间
1	用 dataclass 定义 AgentResult（model / tokens / content / stop_reason）	15 min
2	用推导式从 API 响应提取所有 tool_use block → {id: (name, input)}	15 min
3	用 @contextmanager 写一个 CostTracker，追踪 LLM 调用的耗时和 token 成本	20 min
4	综合：模拟一次 Agent 调用的完整数据流
'''


from contextlib import contextmanager
from dataclasses import dataclass
from collections.abc import Generator
import time
from typing import Literal

# === 1. dataclass 定义数据结构 ===
@dataclass
class Usage:
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0

@dataclass
class AgentResult:
    model: str
    tokens: int
    content: list[dict]
    stop_reason: Literal['end_turn', 'tool_use', 'max_tokens', 'refusal']
    elapsed_ms: float = 0

# === 2. 上下文管理器 ===
@contextmanager
def agent_turn(name: str)->  Generator[dict, None, None]:
    """追踪单次 LLM 调用的耗时和成本"""
    start = time.time()
    stats = { "model": name, "start": start }
    try:
        yield stats
    finally:
        stats["elapsed_ms"] = (time.time() - start) * 1000
        # 计算总成本（这里用示例单价，可自定义）
        input_cost = stats["input_tokens"] * 0.01 / 1000
        output_cost = stats["output_tokens"] * 0.03 / 1000
        total_cost = input_cost + output_cost

        print(f"\n📊 LLM 调用统计 [{stats['model']}]")
        print(f"├─ 耗时：{stats['elapsed_ms']:.2f} ms")
        print(f"├─ 输入 Tokens：{stats['input_tokens']}")
        print(f"├─ 输出 Tokens：{stats['output_tokens']}")
        print(f"├─ 总 Tokens：{stats['total_tokens']}")
        print(f"└─ 估算成本：${total_cost:.4f}")

# === 3. 提取 tool_use ===
def extract_tool_uses(content: list[dict]) -> dict[str, tuple[str, dict]]:
    """从 API 响应提取所有 tool_use 块
    返回 {tool_use_id: (tool_name, input)}
    """
    return {
        block["id"]: (block["name"], block["input"])
        for block in content
        if block.get("type") == "tool_use"
    }


# === 4. 模拟完整流程 ===
def simulate_agent_call(query: str) -> AgentResult:
    mock_response = {
        "model": "claude-opus-4-7",
        "content": [
            {"type": "text", "text": "让我查一下天气"},
            {"type": "tool_use", "id": "toolu_001", "name": "get_weather", "input": {"city": "北京"}},
            {"type": "text", "text": "还需要查时间"},
            {"type": "tool_use", "id": "toolu_002", "name": "get_time", "input": {}},
        ],
        "usage": {"input_tokens": 150, "output_tokens": 80},
        "stop_reason": "tool_use",
    }

    with agent_turn(mock_response["model"]) as stats:
        time.sleep(0.1)  # 模拟 API 调用耗时

         # 赋值 token 信息给统计器
        input_tokens = mock_response["usage"]["input_tokens"]
        output_tokens = mock_response["usage"]["output_tokens"]
        total_tokens = input_tokens + output_tokens
        
        stats["input_tokens"] = input_tokens
        stats["output_tokens"] = output_tokens
        stats["total_tokens"] = total_tokens

        # 模拟处理 API 响应
        content = mock_response["content"]
        tokens = total_tokens
        stop_reason = mock_response["stop_reason"]

        # 提取 tool_use 信息
        tool_uses = extract_tool_uses(content)
        print(f"提取到的 tool_use: {tool_uses}")
    return AgentResult(
        model=mock_response["model"],
        tokens=tokens,
        content=content,
        stop_reason=stop_reason,
        elapsed_ms=stats["elapsed_ms"]
    )
    
if __name__ == "__main__":
    result = simulate_agent_call("今天天气怎么样？")
    print(f"模拟的 Agent 调用结果: 模型-{result}")
    print(f"模拟的 Agent 调用结果: 模型-{result.model}")
    print(f"模拟的 Agent 调用结果: 耗时-{result.elapsed_ms:0f} ms")
    print(f"模拟的 Agent 调用结果: Token-{result.tokens}")
    print(f"模拟的 Agent 调用结果: 原因-{result.stop_reason}")