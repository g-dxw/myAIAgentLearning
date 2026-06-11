"""
Function Calling 手动实现
===========================
本文件演示了 Function Calling 的核心流程，不依赖任何 LLM SDK，
完全手动构造请求、解析响应、执行工具，适合教学和理解原理。

流程:
  1. 定义 Tool Schema（工具的描述和参数结构）
  2. 实现具体工具函数（get_weather / calculate / get_current_time）
  3. execute_tool(): 根据 LLM 返回的工具调用信息执行对应函数
  4. call_with_tools(): 向 LLM 发送请求（带工具定义），获取响应
  5. manual_function_calling(): 演示完整的 Function Calling 一次循环
"""

import json
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib import request, parse


# ============================================================
# 第一步：定义 Tool Schema（工具描述）
# ============================================================
# Tool Schema 遵循 OpenAI 的 function calling 规范格式，
# 告诉 LLM 有哪些工具可用、每个工具的用途和参数结构。

TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "查询指定城市的当前天气信息",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "城市名称，例如：北京、上海、深圳"
                    }
                },
                "required": ["city"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "执行数学计算（加减乘除）",
            "parameters": {
                "type": "object",
                "properties": {
                    "a": {
                        "type": "number",
                        "description": "第一个操作数"
                    },
                    "b": {
                        "type": "number",
                        "description": "第二个操作数"
                    },
                    "op": {
                        "type": "string",
                        "enum": ["+", "-", "*", "/", "add", "subtract", "multiply", "divide"],
                        "description": "运算符：+ 或 add（加）、- 或 subtract（减）、* 或 multiply（乘）、/ 或 divide（除）"
                    }
                },
                "required": ["a", "b", "op"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "获取指定时区的当前日期和时间",
            "parameters": {
                "type": "object",
                "properties": {
                    "timezone": {
                        "type": "string",
                        "description": "时区名称，例如 Asia/Shanghai、America/New_York、UTC",
                        "default": "Asia/Shanghai"
                    }
                },
                "required": ["timezone"]
            }
        }
    }
]


# ============================================================
# 第二步：实现具体的工具函数
# ============================================================

def _get_weather(city: str) -> str:
    """查询城市天气（模拟实现）"""
    # 真实场景可调用 OpenWeatherMap / 和风天气等 API
    # 这里用模拟数据演示
    fake_weather = {
        "北京": {"temperature": 22, "condition": "晴", "humidity": 45, "wind": "3级"},
        "上海": {"temperature": 25, "condition": "多云", "humidity": 70, "wind": "2级"},
        "深圳": {"temperature": 30, "condition": "阵雨", "humidity": 80, "wind": "4级"},
        "广州": {"temperature": 28, "condition": "阴", "humidity": 75, "wind": "3级"},
        "成都": {"temperature": 20, "condition": "小雨", "humidity": 85, "wind": "1级"},
        "杭州": {"temperature": 23, "condition": "晴", "humidity": 55, "wind": "2级"},
    }
    data = fake_weather.get(city, {"temperature": "--", "condition": "未知", "humidity": "--", "wind": "--"})
    return json.dumps({
        "city": city,
        "temperature": f"{data['temperature']}°C",
        "condition": data["condition"],
        "humidity": f"{data['humidity']}%",
        "wind": data["wind"],
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }, ensure_ascii=False)


def _calculate(a: float, b: float, op: str) -> str:
    """执行数学计算"""
    op_map = {
        "+": a + b, "add": a + b,
        "-": a - b, "subtract": a - b,
        "*": a * b, "multiply": a * b,
        "/": a / b if b != 0 else None, "divide": a / b if b != 0 else None,
    }
    result = op_map.get(op)
    if result is None:
        if op in ("/", "divide"):
            return json.dumps({"error": "除数不能为零"}, ensure_ascii=False)
        return json.dumps({"error": f"不支持的运算符: {op}"}, ensure_ascii=False)
    return json.dumps({
        "expression": f"{a} {op} {b}",
        "result": result
    }, ensure_ascii=False)


def _get_current_time(timezone: str = "Asia/Shanghai") -> str:
    """获取指定时区的当前时间"""
    try:
        # 使用 time.tzset 设置时区（仅 Unix）
        # 跨平台方案：构造 UTC 时间信息
        utc_now = datetime.utcnow()
        # 简单时区偏移表（教学演示用，完整实现应使用 pytz / zoneinfo）
        offset_map: Dict[str, int] = {
            "Asia/Shanghai": 8,
            "Asia/Tokyo": 9,
            "Asia/Singapore": 8,
            "Asia/Kolkata": 5 + 30 / 60,  # +5:30
            "America/New_York": -5,
            "America/Chicago": -6,
            "America/Denver": -7,
            "America/Los_Angeles": -8,
            "Europe/London": 0,
            "Europe/Paris": 1,
            "Europe/Berlin": 1,
            "Australia/Sydney": 11,
            "Pacific/Auckland": 13,
            "UTC": 0,
        }
        offset_hours = offset_map.get(timezone, 0)
        # 注意：这里没有考虑夏令时，教学演示简化处理
        local_time = utc_now  # 简化，真实应用应使用 pytz
        return json.dumps({
            "timezone": timezone,
            "utc_offset": f"UTC{offset_hours:+d}",
            "local_time": f"{local_time.hour:02d}:{local_time.minute:02d}:{local_time.second:02d}",
            "date": local_time.strftime("%Y-%m-%d"),
            "note": "时间基于 UTC 偏移近似计算，未考虑夏令时"
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"获取时间失败: {str(e)}"}, ensure_ascii=False)


# 工具名称 -> 实际函数的映射表
FUNCTION_MAP: Dict[str, Callable[..., str]] = {
    "get_weather": _get_weather,
    "calculate": _calculate,
    "get_current_time": _get_current_time,
}

# 工具名称 -> 参数名列表（用于从参数 dict 中提取正确参数）
FUNCTION_PARAMS: Dict[str, List[str]] = {
    "get_weather": ["city"],
    "calculate": ["a", "b", "op"],
    "get_current_time": ["timezone"],
}


# ============================================================
# 第三步：execute_tool() — 根据名称和参数执行对应函数
# ============================================================

def execute_tool(tool_name: str, arguments: Dict[str, Any]) -> str:
    """
    根据工具名称和参数执行对应的工具函数。

    Args:
        tool_name: 工具名称（必须存在于 FUNCTION_MAP 中）
        arguments: 参数字典

    Returns:
        工具执行的返回结果（JSON 字符串）
    """
    if tool_name not in FUNCTION_MAP:
        return json.dumps({"error": f"未知的工具: {tool_name}"}, ensure_ascii=False)

    func = FUNCTION_MAP[tool_name]
    param_names = FUNCTION_PARAMS.get(tool_name, [])

    # 从 arguments 中提取函数需要的参数
    kwargs = {}
    missing = []
    for p in param_names:
        if p in arguments:
            kwargs[p] = arguments[p]
        else:
            missing.append(p)

    if missing:
        return json.dumps({
            "error": f"缺少必要参数: {', '.join(missing)}"
        }, ensure_ascii=False)

    try:
        result = func(**kwargs)
        return result
    except Exception as e:
        return json.dumps({"error": f"工具执行异常: {str(e)}"}, ensure_ascii=False)


# ============================================================
# 第四步：call_with_tools() — 向 LLM 发送请求（带工具定义）
# ============================================================

def call_llm_api(
    messages: List[Dict[str, str]],
    tools: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    向 LLM 发送请求——这里使用模拟方式返回预定义的 Tool Call 响应。
    在实际项目中，应替换为真实的 HTTP 请求调用 LLM API。

    真实场景示例（使用 urllib）:
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        data = json.dumps({"model": "gpt-4", "messages": messages, "tools": tools})
        req = request.Request(url, data=data.encode(), headers=headers, method="POST")
        with request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    """
    # ---------- 模拟 LLM 回复 ----------
    # 为了让演示可重复且不依赖外部 API，
    # 我们根据用户最后一条消息的内容模式匹配，模拟 LLM 的 tool_calls

    last_msg = messages[-1]["content"] if messages else ""

    # ---------- 检查上一轮是否已经执行了工具 ----------
    # 如果最后一条消息是 tool 角色，说明是第二轮——LLM 应基于工具结果生成文本回复
    if messages and messages[-1].get("role") == "tool":
        # 解析工具返回结果，生成自然语言回复
        tool_content = messages[-1].get("content", "{}")
        tool_name = messages[-1].get("name", "")
        try:
            tool_data = json.loads(tool_content)
        except json.JSONDecodeError:
            tool_data = {}

        if tool_name == "get_weather":
            city = tool_data.get("city", "未知")
            cond = tool_data.get("condition", "未知")
            temp = tool_data.get("temperature", "?")
            hum = tool_data.get("humidity", "?")
            wind = tool_data.get("wind", "?")
            choice = {
                "role": "assistant",
                "content": (
                    f"📍 {city}的天气情况如下：\n"
                    f"   🌤️ 天气状况：{cond}\n"
                    f"   🌡️ 温度：{temp}\n"
                    f"   💧 湿度：{hum}\n"
                    f"   🌬️ 风力：{wind}\n\n"
                    f"  (数据获取时间：{tool_data.get('timestamp', '?')})"
                )
            }

        elif tool_name == "calculate":
            expr = tool_data.get("expression", "")
            result = tool_data.get("result", "")
            choice = {
                "role": "assistant",
                "content": f"🧮 计算结果：{expr} = {result}"
            }

        elif tool_name == "get_current_time":
            tz = tool_data.get("timezone", "?")
            lt = tool_data.get("local_time", "?")
            dt = tool_data.get("date", "?")
            offset = tool_data.get("utc_offset", "?")
            choice = {
                "role": "assistant",
                "content": (
                    f"🕐 当前时间（{tz}）\n"
                    f"   📅 日期：{dt}\n"
                    f"   🕰️ 时间：{lt}\n"
                    f"   🌍 时区偏移：{offset}\n"
                    f"   💡 注意：此时间基于 UTC 偏移近似计算，未考虑夏令时。"
                )
            }

        else:
            choice = {
                "role": "assistant",
                "content": f"工具 {tool_name} 返回了结果：{tool_content}"
            }

    else:
        # ---------- 第一轮：根据用户输入关键词判断应该调用哪个工具 ----------
        last_role = messages[-1]["role"]
        last_msg = messages[-1]["content"] if last_role == "user" else ""

        if any(kw in last_msg for kw in ["天气", "温度", "weather", "下雨", "刮风"]):
            # 提取城市名（简单规则）
            cities = ["北京", "上海", "深圳", "广州", "成都", "杭州"]
            city_found = "北京"  # 默认
            for c in cities:
                if c in last_msg:
                    city_found = c
                    break
            choice = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": f"call_{int(time.time())}",
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "arguments": json.dumps({"city": city_found}, ensure_ascii=False)
                        }
                    }
                ]
            }

        elif any(kw in last_msg for kw in ["计算", "加", "减", "乘", "除", "=", "+", "-", "*", "/", "calculate"]):
            # 简单数学表达式提取（演示用）
            import re
            nums = re.findall(r"-?\d+\.?\d*", last_msg)
            a = float(nums[0]) if len(nums) > 0 else 10
            b = float(nums[1]) if len(nums) > 1 else 5
            # 猜测运算符
            if any(k in last_msg for k in ["加", "+", "add"]):
                op = "+"
            elif any(k in last_msg for k in ["减", "-", "subtract"]):
                op = "-"
            elif any(k in last_msg for k in ["乘", "*", "multiply"]):
                op = "*"
            elif any(k in last_msg for k in ["除", "/", "divide"]):
                op = "/"
            else:
                op = "+"
            choice = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": f"call_{int(time.time())}",
                        "type": "function",
                        "function": {
                            "name": "calculate",
                            "arguments": json.dumps({"a": a, "b": b, "op": op}, ensure_ascii=False)
                        }
                    }
                ]
            }

        elif any(kw in last_msg for kw in ["时间", "time", "几点", "时区", "当前时间"]):
            # 提取时区
            tz_map = {
                "上海": "Asia/Shanghai", "北京": "Asia/Shanghai",
                "纽约": "America/New_York", "伦敦": "Europe/London",
                "东京": "Asia/Tokyo", "悉尼": "Australia/Sydney",
            }
            tz = "Asia/Shanghai"
            for cn, tz_name in tz_map.items():
                if cn in last_msg:
                    tz = tz_name
                    break
            choice = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": f"call_{int(time.time())}",
                        "type": "function",
                        "function": {
                            "name": "get_current_time",
                            "arguments": json.dumps({"timezone": tz}, ensure_ascii=False)
                        }
                    }
                ]
            }

        else:
            # 没有匹配到任何工具，LLM 直接回复文本
            choice = {
                "role": "assistant",
                "content": f"你好！我支持以下功能：\n"
                           f"1. 查询天气（例如 '北京天气怎么样？'）\n"
                           f"2. 数学计算（例如 '计算 15 + 27'）\n"
                           f"3. 获取时间（例如 '现在几点？' 或 '纽约时间'）\n"
                           f"请告诉我你需要什么帮助？"
            }

    # 包装成 OpenAI 兼容的响应格式
    return {
        "id": f"chatcmpl-{int(time.time())}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "gpt-4o-mini (simulated)",
        "choices": [{"index": 0, "message": choice, "finish_reason": "tool_calls" if "tool_calls" in choice else "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    }


def call_with_tools(
    messages: List[Dict[str, str]],
    tools: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    向 LLM 发送请求并携带工具定义。

    Args:
        messages: 对话消息列表 [{"role": "user", "content": "..."}, ...]
        tools: 工具定义列表（可选）

    Returns:
        LLM 返回的完整响应
    """
    print(f"\n{'='*60}")
    print(f"📤 [请求] 向 LLM 发送消息（{len(messages)} 条）")
    if tools:
        print(f"📤 [请求] 携带 {len(tools)} 个工具定义")
        for t in tools:
            print(f"        └─ 工具: {t['function']['name']} — {t['function']['description']}")

    response = call_llm_api(messages, tools)

    print(f"📥 [响应] LLM 返回")
    choice = response["choices"][0]
    msg = choice["message"]
    if "tool_calls" in msg:
        print(f"        └─ finish_reason: tool_calls → 请求调用工具")
        for tc in msg["tool_calls"]:
            print(f"             ├─ 工具: {tc['function']['name']}")
            print(f"             └─ 参数: {tc['function']['arguments']}")
    else:
        print(f"        └─ finish_reason: stop → 直接回复文本")
        content = msg.get("content", "")
        print(f"        └─ 内容: {content[:100]}{'...' if len(content) > 100 else ''}")

    return response


# ============================================================
# 第五步：manual_function_calling() — 完整 Function Calling 流程
# ============================================================

def manual_function_calling(user_input: str) -> List[Dict[str, str]]:
    """
    演示一次完整的 Function Calling 流程：
    Step 1: 构造用户消息
    Step 2: 调用 LLM（带工具定义）
    Step 3: 检查 LLM 是否要求调用工具
    Step 4: 执行工具 → 将结果返回给 LLM
    Step 5: LLM 生成最终回复

    Args:
        user_input: 用户的输入文本

    Returns:
        完整的消息历史（可用于继续对话）
    """
    print(f"\n{'★'*35}")
    print(f"★  手动 Function Calling 完整流程演示")
    print(f"{'★'*35}")
    print(f"用户输入: 「{user_input}」")
    print(f"{'★'*35}")

    # Step 1: 初始化消息历史
    messages: List[Dict[str, str]] = [
        {"role": "system", "content": "你是一个智能助手，可以根据用户需求调用工具获取信息或执行计算。"},
        {"role": "user", "content": user_input}
    ]

    # Step 2: 第一轮 —— 发送给 LLM（带工具定义）
    response = call_with_tools(messages, tools=TOOLS)
    assistant_msg = response["choices"][0]["message"]
    messages.append(assistant_msg)

    # Step 3: 检查 LLM 是否想要调用工具
    if "tool_calls" in assistant_msg:
        print(f"\n{'─'*50}")
        print(f"🔧 [Step 3] LLM 请求调用工具，开始执行...")
        print(f"{'─'*50}")

        for tool_call in assistant_msg["tool_calls"]:
            func_name = tool_call["function"]["name"]
            func_args = json.loads(tool_call["function"]["arguments"])

            # Step 4: 执行工具
            print(f"\n▶ 执行工具: {func_name}")
            print(f"  参数: {json.dumps(func_args, ensure_ascii=False)}")
            result = execute_tool(func_name, func_args)
            print(f"  结果: {result}")

            # 将工具执行结果追加到消息历史
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "name": func_name,
                "content": result
            })

        # Step 5: 将工具结果送回 LLM 生成最终回复
        print(f"\n{'─'*50}")
        print(f"💬 [Step 5] 将工具结果送回 LLM，等待最终回复...")
        print(f"{'─'*50}")

        final_response = call_with_tools(messages)  # 不再传 tools，让 LLM 直接回复
        final_msg = final_response["choices"][0]["message"]
        messages.append(final_msg)

        print(f"\n📢 [最终回复]")
        print(f"{final_msg.get('content', '')}")

    else:
        # LLM 直接回复，未调用工具
        print(f"\n📢 [回复]")
        print(f"{assistant_msg.get('content', '')}")

    return messages


# ============================================================
# 第六步：if __name__ 演示入口
# ============================================================

def demo_basic_execution():
    """演示直接调用单个工具函数"""
    print(f"\n{'#'*50}")
    print(f"#  演示 1: 直接执行工具函数")
    print(f"{'#'*50}")

    # 查询北京天气
    result = execute_tool("get_weather", {"city": "北京"})
    print(f"\n▶ execute_tool('get_weather', {{'city': '北京'}})")
    print(f"  结果: {result}")

    # 计算 25 * 4
    result = execute_tool("calculate", {"a": 25, "b": 4, "op": "*"})
    print(f"\n▶ execute_tool('calculate', {{'a': 25, 'b': 4, 'op': '*'}})")
    print(f"  结果: {result}")

    # 查看当前时间
    result = execute_tool("get_current_time", {"timezone": "America/New_York"})
    print(f"\n▶ execute_tool('get_current_time', {{'timezone': 'America/New_York'}})")
    print(f"  结果: {result}")

    # 测试错误处理：不存在的工具
    result = execute_tool("send_email", {"to": "test@example.com"})
    print(f"\n▶ execute_tool('send_email', ...)  # 不存在的工具")
    print(f"  结果: {result}")


def demo_full_flow_weather():
    """演示完整的天气查询 Function Calling 流程"""
    manual_function_calling("请问今天北京的天气怎么样？")


def demo_full_flow_calculate():
    """演示完整的数学计算 Function Calling 流程"""
    manual_function_calling("帮我计算 1234 乘以 567 等于多少？")


def demo_full_flow_time():
    """演示完整的时区时间查询 Function Calling 流程"""
    manual_function_calling("告诉我现在纽约的时间？")


def demo_tool_schema_preview():
    """展示完整的 Tool Schema 结构"""
    print(f"\n{'#'*50}")
    print(f"#  Tool Schema 预览")
    print(f"{'#'*50}")
    print(f"\n共定义 {len(TOOLS)} 个工具:\n")
    print(json.dumps(TOOLS, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    print(f"{'='*55}")
    print(f"  Function Calling 手动实现 — 教学演示")
    print(f"{'='*55}")

    # ---------- 演示工具 Schema ----------
    demo_tool_schema_preview()

    # ---------- 演示 1: 基础工具执行 ----------
    demo_basic_execution()

    # ---------- 演示 2: 完整 Function Calling 流程（天气）----------
    print(f"\n{'='*55}")
    print(f"  完整流程演示即将开始...")
    print(f"{'='*55}")
    demo_full_flow_weather()

    # ---------- 演示 3: 数学计算 ----------
    demo_full_flow_calculate()

    # ---------- 演示 4: 时区时间 ----------
    demo_full_flow_time()

    print(f"\n{'='*55}")
    print(f"  演示结束 — 感谢阅读！")
    print(f"{'='*55}")
