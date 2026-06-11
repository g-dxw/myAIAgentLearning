"""
Agent Loop 框架 — Day 03 教程
==============================
ToolAgent 类：封装消息管理、工具注册、循环控制的核心 Agent 框架。
支持 OpenAI 兼容 API，内置工具示例，含循环检测与 Token 统计。
"""

import json
import time
import re
from typing import Any, Callable, Optional
from datetime import datetime

# ============================================================
# ToolAgent 类
# ============================================================

class ToolAgent:
    """
    一个通用的 Agent Loop 框架。

    核心流程：
        1. 接收用户输入
        2. 调用 LLM（大语言模型）获取回复
        3. 如果回复包含工具调用 → 执行工具 → 返回步骤 2
        4. 如果回复是纯文本 → 返回给用户
    """

    def __init__(
        self,
        system_prompt: Optional[str] = None,
        tools: Optional[dict[str, dict]] = None,
        handlers: Optional[dict[str, Callable]] = None,
        max_turns: int = 10,
        model: str = "gpt-4o-mini",
        api_base: str = "https://api.openai.com/v1",
        api_key: Optional[str] = None,
    ):
        """
        初始化 Agent。

        参数:
            system_prompt: 系统提示词（角色设定）
            tools:         工具定义字典，key=工具名，value=工具描述/参数字典
            handlers:      工具处理函数字典，key=工具名，value=可调用函数
            max_turns:     最大循环轮数，防止死循环
            model:         LLM 模型名称
            api_base:      API 端点地址
            api_key:       API 密钥（默认从环境变量 OPENAI_API_KEY 读取）
        """
        self.system_prompt = system_prompt or self._default_system_prompt()
        self.tools = tools or {}
        self.handlers = handlers or {}
        self.max_turns = max_turns
        self.model = model
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key

        # ---- 运行时状态 ----
        self.messages: list[dict] = []          # 对话消息历史
        self.turns_used: int = 0                 # 已使用的工具调用轮数
        self.total_prompt_tokens: int = 0        # 累计 prompt token 数
        self.total_completion_tokens: int = 0    # 累计 completion token 数
        self.total_tokens: int = 0               # 累计总 token 数
        self._loop_count: int = 0                # 当前 run 的内循环计数器

    # ---------- 默认系统提示词 ----------

    def _default_system_prompt(self) -> str:
        """默认系统提示词，引导 Agent 使用工具。"""
        return (
            "你是一个有用的 AI 助手，可以通过调用工具来获取实时信息或进行计算。"
            "当用户的问题需要工具时，请调用对应的工具函数。"
            "请始终用中文回复。"
        )

    # ---------- 默认内置工具 ----------

    @staticmethod
    def get_weather(city: str) -> str:
        """
        获取指定城市的当前天气（模拟数据）。

        参数:
            city: 城市名称，如 "北京"

        返回:
            天气描述字符串
        """
        # 模拟天气数据 — 真实场景应调用第三方 API
        mock_data = {
            "北京": "晴，25°C，湿度 40%，西北风 3 级",
            "上海": "多云，28°C，湿度 65%，东南风 2 级",
            "深圳": "阵雨，30°C，湿度 80%，南风 4 级",
            "广州": "雷阵雨，29°C，湿度 85%，西南风 3 级",
            "成都": "阴，22°C，湿度 70%，北风 2 级",
            "杭州": "晴转多云，26°C，湿度 55%，东风 3 级",
            "武汉": "小雨，23°C，湿度 78%，东北风 2 级",
            "南京": "多云，24°C，湿度 60%，东风 2 级",
        }
        data = mock_data.get(city, f"{city}：暂无天气数据（模拟）")
        return f"📍 {city} 天气：{data}"

    @staticmethod
    def calculate(expression: str) -> str:
        """
        计算数学表达式。

        参数:
            expression: 数学表达式字符串，如 "1 + 2 * 3"

        返回:
            计算结果字符串
        """
        # 安全评估：仅允许数字、运算符和括号
        safe_pattern = r"^[\d+\-*/().%^, ]+$"
        if not re.match(safe_pattern, expression.strip()):
            return f"❌ 表达式包含非法字符：{expression}"

        try:
            # 使用 eval 的安全受限版本
            result = eval(expression, {"__builtins__": {}}, {})
            return f"📐 {expression} = {result}"
        except Exception as e:
            return f"❌ 计算错误：{e}"

    @staticmethod
    def get_current_time(timezone: str = "Asia/Shanghai") -> str:
        """
        获取当前日期和时间。

        参数:
            timezone: 时区名称（仅用于显示），如 "Asia/Shanghai", "America/New_York"

        返回:
            当前时间字符串
        """
        now = datetime.now()
        return (
            f"🕐 当前时间：{now.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"📅 星期：{['一', '二', '三', '四', '五', '六', '日'][now.weekday()]}\n"
            f"🌍 时区：{timezone}"
        )

    # ---------- 注册默认工具 ----------

    def register_default_tools(self):
        """注册内置的三个示例工具。"""
        self.tools.update({
            "get_weather": {
                "description": "获取指定城市的当前天气",
                "parameters": {
                    "city": {
                        "type": "string",
                        "description": "城市名称，如 '北京'",
                        "required": True,
                    }
                },
            },
            "calculate": {
                "description": "计算数学表达式",
                "parameters": {
                    "expression": {
                        "type": "string",
                        "description": "数学表达式，如 '1 + 2 * 3'",
                        "required": True,
                    }
                },
            },
            "get_current_time": {
                "description": "获取当前日期和时间",
                "parameters": {
                    "timezone": {
                        "type": "string",
                        "description": "时区名称，默认 'Asia/Shanghai'",
                        "required": False,
                    }
                },
            },
        })

        # 将静态方法绑定为处理器
        self.handlers.update({
            "get_weather": self.get_weather,
            "calculate": self.calculate,
            "get_current_time": self.get_current_time,
        })

    # ---------- 工具注册方法 ----------

    def register_tool(
        self,
        name: str,
        description: str,
        parameters: dict,
        handler: Callable,
    ):
        """
        注册一个自定义工具。

        参数:
            name:        工具名称
            description: 工具描述
            parameters:  参数定义字典（与 OpenAI function calling 格式兼容）
            handler:     工具处理函数
        """
        self.tools[name] = {"description": description, "parameters": parameters}
        self.handlers[name] = handler

    # ---------- 构建工具定义（OpenAI 格式） ----------

    def _build_tool_definitions(self) -> list[dict]:
        """将内部工具字典转换为 OpenAI function calling 格式。"""
        definitions = []
        for name, meta in self.tools.items():
            props = {}
            required = []
            for param_name, param_meta in meta.get("parameters", {}).items():
                props[param_name] = {
                    "type": param_meta.get("type", "string"),
                    "description": param_meta.get("description", ""),
                }
                if param_meta.get("required", False):
                    required.append(param_name)

            definitions.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": meta["description"],
                    "parameters": {
                        "type": "object",
                        "properties": props,
                        "required": required,
                    },
                },
            })
        return definitions

    # ---------- 检测工具循环 ----------

    def _detect_tool_loop(self) -> bool:
        """
        检测是否陷入了工具调用循环。
        规则：连续 3 次调用同一个工具且参数完全相同 → 判定为循环。
        """
        tool_calls_in_history = []
        for msg in self.messages:
            if msg.get("role") == "assistant" and "tool_calls" in msg:
                for tc in msg["tool_calls"]:
                    tool_calls_in_history.append({
                        "name": tc["function"]["name"],
                        "args": tc["function"]["arguments"],
                    })

        # 检查最近 N 次
        n = min(3, len(tool_calls_in_history))
        if n < 3:
            return False

        recent = tool_calls_in_history[-n:]
        first = recent[0]
        return all(
            call["name"] == first["name"] and call["args"] == first["args"]
            for call in recent
        )

    # ---------- 调用 LLM ----------

    def call_llm(self) -> str:
        """
        调用 OpenAI 兼容 API，获取 LLM 回复。

        返回:
            LLM 回复内容字符串

        抛出:
            ConnectionError: API 连接失败时
        """
        import httpx

        # 构建请求体
        payload = {
            "model": self.model,
            "messages": self.messages,
        }

        # 如果注册了工具，附加工具定义
        if self.tools:
            payload["tools"] = self._build_tool_definitions()
            payload["tool_choice"] = "auto"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key or ''}",
        }

        # 发送请求
        try:
            with httpx.Client(timeout=60.0) as client:
                response = client.post(
                    f"{self.api_base}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
                result = response.json()
        except Exception as e:
            raise ConnectionError(f"API 调用失败：{e}") from e

        # 提取回复
        choice = result["choices"][0]
        message = choice["message"]

        # ---- 记录 Token 用量 ----
        usage = result.get("usage", {})
        self.total_prompt_tokens += usage.get("prompt_tokens", 0)
        self.total_completion_tokens += usage.get("completion_tokens", 0)
        self.total_tokens += usage.get("total_tokens", 0)

        return message

    # ---------- 执行工具 ----------

    def _execute_tool(self, tool_name: str, tool_args: dict) -> str:
        """
        执行指定的工具函数。

        参数:
            tool_name: 工具名称
            tool_args: 工具参数字典

        返回:
            工具执行结果字符串

        抛出:
            ValueError: 工具不存在时
        """
        if tool_name not in self.handlers:
            return f"❌ 未知工具：{tool_name}"

        handler = self.handlers[tool_name]
        try:
            # 尝试调用：支持有参 / 无参
            result = handler(**tool_args) if tool_args else handler()
            return str(result)
        except TypeError as e:
            return f"❌ 工具参数错误：{e}"
        except Exception as e:
            return f"❌ 工具执行异常：{e}"

    # ---------- 从消息中提取工具调用 ----------

    def _extract_tool_calls(self, message: dict) -> list[dict]:
        """
        从 LLM 回复消息中提取工具调用。

        支持两种格式：
            1. OpenAI function calling 原生格式（message.tool_calls）
            2. 文本格式，如
               ═══ TOOL_CALL: tool_name ═══
               {"key": "value"}
               ═══ END TOOL_CALL ═══
        """
        tool_calls = []

        # 格式 1：原生 function calling
        if "tool_calls" in message:
            for tc in message["tool_calls"]:
                try:
                    args = json.loads(tc["function"]["arguments"])
                except (json.JSONDecodeError, KeyError):
                    args = {}
                tool_calls.append({
                    "id": tc.get("id", ""),
                    "name": tc["function"]["name"],
                    "arguments": args,
                })

        # 格式 2：文本包裹格式（用于不支持原生 tool_calls 的模型）
        content = message.get("content", "")
        if content:
            pattern = r"═══ TOOL_CALL: (\w+) ═══\n(.*?)\n═══ END TOOL_CALL ═══"
            for match in re.finditer(pattern, content, re.DOTALL):
                name = match.group(1)
                try:
                    args = json.loads(match.group(2).strip())
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append({
                    "id": f"call_{name}_{int(time.time())}",
                    "name": name,
                    "arguments": args,
                })

        return tool_calls

    # ---------- Agent Loop 主方法 ----------

    def run(self, user_input: str) -> str:
        """
        Agent Loop 主入口。

        流程：
            1. 追加用户消息
            2. 调用 LLM
            3. 如果 LLM 返回工具调用 → 执行 → 追加结果 → 回到步骤 2
            4. 如果 LLM 返回纯文本 → 返回最终回复

        参数:
            user_input: 用户输入字符串

        返回:
            Agent 的最终回复字符串
        """
        # ---- 重置运行状态 ----
        self.messages = []
        self.turns_used = 0
        self._loop_count = 0

        # 注入系统提示词
        self.messages.append({"role": "system", "content": self.system_prompt})

        # 追加用户消息
        self.messages.append({"role": "user", "content": user_input})

        # ---- Agent Loop ----
        while self._loop_count < self.max_turns:
            self._loop_count += 1

            # 1. 调用 LLM
            try:
                assistant_message = self.call_llm()
            except ConnectionError as e:
                error_msg = f"🔴 Agent 错误：{e}"
                self.messages.append({"role": "assistant", "content": error_msg})
                return error_msg

            # 2. 将 LLM 回复追加到消息历史
            self.messages.append(assistant_message)

            # 3. 提取工具调用
            tool_calls = self._extract_tool_calls(assistant_message)

            # 4. 没有工具调用 → 返回文本回复
            if not tool_calls:
                return assistant_message.get("content", "") or "(空回复)"

            # 5. 有工具调用 → 逐一执行
            self.turns_used += len(tool_calls)

            # 循环检测
            if self._detect_tool_loop():
                warning = (
                    "⚠️ 检测到工具调用循环！"
                    f"连续 {self.turns_used} 次调用相同的工具。"
                    "已终止循环，请用文字回答用户问题。"
                )
                self.messages.append({
                    "role": "assistant",
                    "content": warning,
                })
                return warning

            # 执行每个工具
            for tc in tool_calls:
                tool_name = tc["name"]
                tool_args = tc["arguments"]
                result = self._execute_tool(tool_name, tool_args)

                # 追加工具执行结果（OpenAI 格式）
                self.messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "name": tool_name,
                    "content": result,
                })

            # 继续循环：让 LLM 处理工具结果后再决定下一步

        # ---- 超过最大轮数 ----
        timeout_msg = (
            f"⏰ 已达到最大工具调用轮数（{self.max_turns} 轮），"
            "Agent 循环自动终止。"
        )
        self.messages.append({"role": "assistant", "content": timeout_msg})
        return timeout_msg

    # ---------- 统计信息 ----------

    def get_stats(self) -> dict[str, Any]:
        """获取当前 Agent 的统计信息。"""
        return {
            "turns_used": self.turns_used,
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_tokens,
            "model": self.model,
            "max_turns": self.max_turns,
            "tools_count": len(self.tools),
            "messages_count": len(self.messages),
        }

    def print_stats(self):
        """打印统计信息到控制台。"""
        stats = self.get_stats()
        print("=" * 50)
        print("📊 Agent 统计")
        print("=" * 50)
        print(f"  模型：         {stats['model']}")
        print(f"  工具调用轮数：  {stats['turns_used']}")
        print(f"  消息数量：      {stats['messages_count']}")
        print(f"  注册工具数：    {stats['tools_count']}")
        print(f"  Prompt Token：  {stats['total_prompt_tokens']:,}")
        print(f"  Completion：    {stats['total_completion_tokens']:,}")
        print(f"  总 Token：      {stats['total_tokens']:,}")
        print("=" * 50)


# ============================================================
# 演示 / 测试
# ============================================================

def demo():
    """
    演示 ToolAgent 的基本用法。

    注意：需要设置 OPENAI_API_KEY 环境变量，或修改 api_key 参数。
    """
    # 创建 Agent 实例
    agent = ToolAgent(
        system_prompt=(
            "你是一个智能助手，可以使用工具来回答用户的问题。"
            "当需要天气信息时调用 get_weather，需要计算时调用 calculate，"
            "需要时间时调用 get_current_time。"
            "请用中文回复。"
        ),
        model="gpt-4o-mini",
        max_turns=5,
    )

    # 注册默认工具
    agent.register_default_tools()

    print("=" * 60)
    print("🤖 Agent Loop 演示")
    print("=" * 60)
    print()

    # ---- 测试 1：天气查询 ----
    print("▶ 测试 1：天气查询")
    print(f"   用户：北京今天天气怎么样？")
    result = agent.run("北京今天天气怎么样？")
    print(f"   Agent：{result}")
    agent.print_stats()
    print()

    # ---- 测试 2：计算 ----
    print("▶ 测试 2：数学计算")
    print(f"   用户：计算 (15 + 27) * 3 等于多少？")
    result = agent.run("计算 (15 + 27) * 3 等于多少？")
    print(f"   Agent：{result}")
    agent.print_stats()
    print()

    # ---- 测试 3：时间 ----
    print("▶ 测试 3：当前时间")
    print(f"   用户：现在几点了？")
    result = agent.run("现在几点了？")
    print(f"   Agent：{result}")
    agent.print_stats()
    print()

    # ---- 测试 4：混合查询 ----
    print("▶ 测试 4：混合查询")
    print(f"   用户：北京天气怎么样？深圳呢？")
    result = agent.run("北京天气怎么样？深圳呢？")
    print(f"   Agent：{result}")
    agent.print_stats()
    print()

    print("=" * 60)
    print("✅ 演示完成")
    print("=" * 60)


# ============================================================
# 入口
# ============================================================

if __name__ == "__main__":
    demo()
