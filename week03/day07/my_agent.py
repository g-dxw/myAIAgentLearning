"""
my_agent.py — 完整的多工具 Agent（Week 03 产出）

核心：
- Agent = LLM(决策) + Tools(能力) + Loop(控制流)
- 不依赖 LangChain/CrewAI，全部手写
- 支持模拟模式（无 API key 也能跑）

用法：
  python my_agent.py              # 交互模式
  python my_agent.py --demo       # 运行所有测试
"""
import json
import os
import re
import sys
from datetime import datetime
from typing import Callable


class MyAgent:
    """
    完整 Agent 实现。

    设计要点：
    - messages 是唯一的状态源
    - 每轮都在 messages 尾部追加，不修改已有消息
    - 工具结果用 tool 角色，不混入 user/assistant
    - 错误通过 tool 结果返回给 LLM，不在 Agent 层抛异常
    """

    def __init__(
        self,
        system_prompt: str | None = None,
        model: str = "gpt-4o",
        api_key: str = "",
        base_url: str = "https://api.openai.com/v1",
        max_turns: int = 15,
    ):
        self.model = model
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.base_url = base_url
        self.max_turns = max_turns
        self._use_mock = not bool(self.api_key)

        # 工具注册表
        self.tools: list[dict] = []
        self.handlers: dict[str, Callable] = {}
        self._register_default_tools()

        # 笔记存储
        self._notes: dict[str, str] = {}

        # 系统提示词
        self.system_prompt = system_prompt or """你是一个功能强大的 AI 助手。
你有多种工具可以使用，请根据用户需求选择合适的工具。
如果工具返回错误，请尝试其他方法或告诉用户。
用中文回答。"""

        # 统计
        self.reset_stats()

        # 工具循环检测
        self._last_tool_calls: list[tuple[str, str]] = []

    def reset_stats(self):
        self.total_turns = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.tool_call_count = 0

    def get_stats(self) -> dict:
        return {
            "turns": self.total_turns,
            "tool_calls": self.tool_call_count,
            "input_tokens": self.total_input_tokens,
            "output_tokens": self.total_output_tokens,
        }

    # ==========================================
    # 工具注册
    # ==========================================

    def register_tool(self, schema: dict, handler: Callable):
        """注册一个新工具"""
        self.tools.append(schema)
        name = schema["function"]["name"]
        self.handlers[name] = handler

    def _register_default_tools(self):
        """注册默认工具集"""

        # 1. 天气查询
        self.register_tool(
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "获取指定城市的当前天气。输入城市名，返回温度、天气状况、湿度。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "city": {
                                "type": "string",
                                "description": "城市名，如 北京、上海、广州、深圳",
                            },
                        },
                        "required": ["city"],
                    },
                },
            },
            self._handle_weather,
        )

        # 2. 数学计算
        self.register_tool(
            {
                "type": "function",
                "function": {
                    "name": "calculate",
                    "description": "执行数学计算。支持加减乘除、括号、幂运算。例如：1024 * 768, (15+25)*2, 2**10",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "expression": {
                                "type": "string",
                                "description": "数学表达式",
                            },
                        },
                        "required": ["expression"],
                    },
                },
            },
            self._handle_calculate,
        )

        # 3. 当前时间
        self.register_tool(
            {
                "type": "function",
                "function": {
                    "name": "get_current_time",
                    "description": "获取当前的日期和时间。不依赖外部 API。",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            self._handle_time,
        )

        # 4. 网络搜索
        self.register_tool(
            {
                "type": "function",
                "function": {
                    "name": "search_web",
                    "description": "搜索互联网获取信息。当需要实时数据、新闻、或你不知道的知识时调用。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "搜索关键词",
                            },
                            "max_results": {
                                "type": "integer",
                                "description": "返回结果数，默认 3",
                                "default": 3,
                            },
                        },
                        "required": ["query"],
                    },
                },
            },
            self._handle_search,
        )

        # 5. 保存笔记
        self.register_tool(
            {
                "type": "function",
                "function": {
                    "name": "save_note",
                    "description": "保存一条笔记。当用户说'记住'或'记下来'时调用。笔记会被存储。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "key": {
                                "type": "string",
                                "description": "笔记的键，如 user_favorite_color",
                            },
                            "value": {
                                "type": "string",
                                "description": "笔记内容",
                            },
                        },
                        "required": ["key", "value"],
                    },
                },
            },
            self._handle_save_note,
        )

        # 6. 检索笔记
        self.register_tool(
            {
                "type": "function",
                "function": {
                    "name": "get_note",
                    "description": "检索已保存的笔记。当用户说'我之前说过'或'还记得吗'时调用。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "key": {
                                "type": "string",
                                "description": "笔记的键",
                            },
                        },
                        "required": ["key"],
                    },
                },
            },
            self._handle_get_note,
        )

    # ==========================================
    # 工具 Handler
    # ==========================================

    def _handle_weather(self, city: str) -> dict:
        """模拟天气查询"""
        import random
        conditions = ["晴", "多云", "阴", "小雨", "晴转多云"]
        return {
            "city": city,
            "temperature": random.randint(15, 35),
            "condition": random.choice(conditions),
            "humidity": random.randint(30, 80),
            "query_time": datetime.now().strftime("%H:%M"),
        }

    def _handle_calculate(self, expression: str) -> dict:
        """安全数学计算"""
        allowed = set("0123456789+-*/.()% ")
        if not all(c in allowed for c in expression):
            return {"error": "表达式包含非法字符", "expression": expression}
        if re.search(r'__|[a-zA-Z]', expression):
            return {"error": "不允使用字母", "expression": expression}
        try:
            result = eval(expression)  # 教学演示，生产用 numexpr
            return {"expression": expression, "result": result}
        except Exception as e:
            return {"error": f"计算错误: {e}", "expression": expression}

    def _handle_time(self) -> dict:
        now = datetime.now()
        return {
            "datetime": now.isoformat(),
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M:%S"),
            "weekday": ["周一","周二","周三","周四","周五","周六","周日"][now.weekday()],
        }

    def _handle_search(self, query: str, max_results: int = 3) -> dict:
        """搜索互联网（DuckDuckGo）"""
        try:
            import httpx
            resp = httpx.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10,
            )
            results = []
            for item in resp.text.split('<a rel="nofollow" href="')[1:max_results+1]:
                url = item.split('"')[0]
                title_match = re.search(r'class="result__title".*?>(.*?)</a>', item, re.DOTALL)
                snippet_match = re.search(r'class="result__snippet".*?>(.*?)</', item, re.DOTALL)
                title = re.sub(r'<[^>]+>', '', title_match.group(1)) if title_match else url
                snippet = re.sub(r'<[^>]+>', '', snippet_match.group(1)) if snippet_match else ""
                results.append({"title": title.strip(), "url": url, "snippet": snippet.strip()})
            return {"query": query, "results": results, "total": len(results)}
        except Exception as e:
            return {"query": query, "results": [], "error": str(e)}

    def _handle_save_note(self, key: str, value: str) -> dict:
        self._notes[key] = value
        return {"status": "saved", "key": key}

    def _handle_get_note(self, key: str) -> dict:
        value = self._notes.get(key)
        if value:
            return {"key": key, "value": value, "found": True}
        return {"key": key, "found": False, "message": f"未找到键为 '{key}' 的笔记"}

    # ==========================================
    # LLM 调用（模拟模式）
    # ==========================================

    def _call_llm(self, messages: list[dict]) -> dict:
        """
        调用 LLM API。无 API key 时使用模拟模式。
        """
        if self._use_mock:
            return self._mock_call_llm(messages)

        import httpx
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": self.model,
            "messages": messages,
            "tools": self.tools,
            "tool_choice": "auto",
        }
        with httpx.Client(timeout=120) as client:
            resp = client.post(
                f"{self.base_url}/chat/completions",
                headers=headers, json=body,
            )
            resp.raise_for_status()
            data = resp.json()
            if "usage" in data:
                self.total_input_tokens += data["usage"].get("prompt_tokens", 0)
                self.total_output_tokens += data["usage"].get("completion_tokens", 0)
            return data

    def _mock_call_llm(self, messages: list[dict]) -> dict:
        """
        模拟 LLM 调用（无 API key 时使用）。

        根据用户输入智能判断需要调用的工具。
        """
        last_user = ""
        for m in reversed(messages):
            if m["role"] == "user":
                last_user = m["content"]
                break

        # 检查是否最后有 tool 结果需要整合
        last_is_tool = messages and messages[-1]["role"] == "tool"

        if last_is_tool:
            # 模拟 LLM 整合工具结果 —— 从所有 tool 消息中提取关键信息
            tool_results = []
            for m in reversed(messages):
                if m["role"] == "tool":
                    tool_results.append(m["content"])

            if tool_results:
                # 尝试解析并整合
                integrated = ""
                for r_str in tool_results:
                    try:
                        r_data = json.loads(r_str)
                        if "result" in r_data:
                            integrated += f"计算结果: {r_data['result']}。"
                        elif "temperature" in r_data:
                            integrated += f"{r_data['city']}天气: {r_data['temperature']}°C，{r_data['condition']}，湿度{r_data['humidity']}%。"
                        elif "time" in r_data:
                            integrated += f"当前时间: {r_data['date']} {r_data['time']}，{r_data['weekday']}。"
                        elif "results" in r_data and r_data["results"]:
                            integrated += f"搜索到 {r_data['total']} 条结果: "
                            for i, r in enumerate(r_data["results"][:2]):
                                integrated += f"{i+1}. {r['title']} "
                        elif "value" in r_data and r_data.get("found"):
                            integrated += f"笔记内容: {r_data['value']}。"
                        elif "found" in r_data and not r_data["found"]:
                            integrated += f"没有找到相关笔记。"
                        elif "status" in r_data:
                            integrated += f"已记录。"
                        else:
                            integrated += f"查询结果: {r_str[:100]}。"
                    except json.JSONDecodeError:
                        integrated += r_str[:100] + "。"

                if integrated:
                    return {
                        "choices": [{
                            "message": {
                                "role": "assistant",
                                "content": integrated,
                            }
                        }],
                        "usage": {"prompt_tokens": 50, "completion_tokens": 30},
                    }

            return {
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": "查询完毕，以上是您需要的信息。",
                    }
                }],
                "usage": {"prompt_tokens": 50, "completion_tokens": 20},
            }

        # 判断是否需要工具调用
        tool_calls = []

        if any(kw in last_user for kw in ["天气", "温度", "多少度", "热吗", "冷吗"]):
            # 提取城市名
            cities = re.findall(r'北京|上海|广州|深圳|杭州|成都|武汉|南京|天津|重庆|西安', last_user)
            city = (cities[0]) if cities else "北京市"
            tool_calls.append({
                "id": "mock_tc_1",
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "arguments": json.dumps({"city": city}, ensure_ascii=False),
                },
            })

        if any(kw in last_user for kw in ["计算", "等于", "多少", "+", "-", "*", "/", "×", "加", "减", "乘", "除"]):
            # 提取数学表达式
            expr_match = re.search(r'([\d+\-*/.()%\s×x]+)', last_user)
            if expr_match:
                expr = expr_match.group(1).replace("×", "*").replace("x", "*").strip()
                if expr:
                    tool_calls.append({
                        "id": "mock_tc_2",
                        "type": "function",
                        "function": {
                            "name": "calculate",
                            "arguments": json.dumps({"expression": expr}, ensure_ascii=False),
                        },
                    })

        if any(kw in last_user for kw in ["时间", "几点了", "日期", "今天", "星期"]):
            tool_calls.append({
                "id": "mock_tc_3",
                "type": "function",
                "function": {
                    "name": "get_current_time",
                    "arguments": "{}",
                },
            })

        if any(kw in last_user for kw in ["搜索", "查一下", "找一下", "百度", "搜一下"]):
            query = last_user
            for prefix in ["搜索", "查一下", "找一下", "百度", "搜一下"]:
                query = query.replace(prefix, "")
            query = query.strip().rstrip("。，！？")
            if query:
                tool_calls.append({
                    "id": "mock_tc_4",
                    "type": "function",
                    "function": {
                        "name": "search_web",
                        "arguments": json.dumps({"query": query, "max_results": 3}, ensure_ascii=False),
                    },
                })

        if any(kw in last_user for kw in ["记住", "记下来", "记一下", "记得"]):
            # 提取 key-value 对（支持"XX是YY"和"我喜欢XX"两种格式）
            content = last_user
            for prefix in ["记住", "记下来", "记一下", "记得"]:
                content = content.replace(prefix, "")
            content = content.strip().rstrip("。，！？")
            if "是" in content and len(content.split("是", 1)) == 2:
                key_part, value = content.split("是", 1)
                key = "user_" + key_part.strip().replace(" ", "_")
                value = value.strip()
            else:
                # 格式：记住我喜欢蓝色 → key=user_favorite, value=我喜欢蓝色
                key = "user_favorite"
                value = content
            tool_calls.append({
                "id": "mock_tc_5",
                "type": "function",
                "function": {
                    "name": "save_note",
                    "arguments": json.dumps({"key": key, "value": value}, ensure_ascii=False),
                },
            })

        if any(kw in last_user for kw in ["什么", "记得", "笔记", "之前", "我"]):
            if any(kw in last_user for kw in ["颜色", "喜欢", "名字", "年龄", "住"]):
                # 尝试检索笔记——匹配多个可能的 key
                possible_keys = []
                if "颜色" in last_user:
                    possible_keys.append("user_我最喜欢的颜色")
                if "名字" in last_user or "姓名" in last_user:
                    possible_keys.append("user_我的名字")
                if "年龄" in last_user:
                    possible_keys.append("user_我的年龄")
                # 通用 fallback
                possible_keys.append("user_favorite")
                # 取第一个存在的 key
                target_key = possible_keys[0]
                for k in possible_keys:
                    if k in self._notes:
                        target_key = k
                        break
                tool_calls.append({
                    "id": "mock_tc_6",
                    "type": "function",
                    "function": {
                        "name": "get_note",
                        "arguments": json.dumps({"key": target_key}, ensure_ascii=False),
                    },
                })

        # 如果没有匹配到工具，或者有工具但最后一个消息是 tool 结果，返回文本
        if not tool_calls:
            return {
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": f"你好！我是 MyAgent，可以使用以下工具帮你：\n"
                                   f"- 查询天气\n- 数学计算\n- 查看时间日期\n"
                                   f"- 网络搜索\n- 笔记记录\n\n你想做什么？",
                    }
                }],
                "usage": {"prompt_tokens": 30, "completion_tokens": 40},
            }

        return {
            "choices": [{"message": {"role": "assistant", "tool_calls": tool_calls}}],
            "usage": {"prompt_tokens": 40, "completion_tokens": 15},
        }

    # ==========================================
    # 工具循环检测
    # ==========================================

    def _detect_tool_loop(self, tool_calls: list[dict]) -> bool:
        """
        检测 LLM 是否陷入工具循环。

        如果连续两轮调用完全相同的工具+参数，判定为循环。
        """
        current = sorted([
            (tc["function"]["name"], tc["function"]["arguments"])
            for tc in tool_calls
        ])
        if self._last_tool_calls and current == self._last_tool_calls:
            return True
        self._last_tool_calls = current
        return False

    # ==========================================
    # 主循环
    # ==========================================

    def run(self, user_input: str, verbose: bool = False) -> str:
        """
        主入口：接受用户输入，返回 Agent 回答。
        """
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_input},
        ]

        self._last_tool_calls = []

        for turn in range(self.max_turns):
            self.total_turns += 1
            loop_count = 0

            # 调 LLM
            response = self._call_llm(messages)
            assistant_msg = response["choices"][0]["message"]

            # 无 tool_calls → 最终回答
            if not assistant_msg.get("tool_calls"):
                final_text = assistant_msg.get("content", "") or ""
                return final_text

            # 工具循环检测
            if self._detect_tool_loop(assistant_msg["tool_calls"]):
                return "⚠️ 检测到工具循环（连续两次相同的工具调用），已自动停止。请换个问法试试。"

            # 有 tool_calls → 执行
            messages.append(assistant_msg)

            for tc in assistant_msg["tool_calls"]:
                func_name = tc["function"]["name"]
                func_args = json.loads(tc["function"]["arguments"])
                self.tool_call_count += 1
                loop_count += 1

                if verbose:
                    print(f"  🔧 {func_name}({json.dumps(func_args, ensure_ascii=False)[:60]})")

                handler = self.handlers.get(func_name)
                if handler:
                    try:
                        result = handler(**func_args)
                    except Exception as e:
                        result = {"error": f"工具执行失败: {e}"}
                else:
                    result = {"error": f"未知工具: {func_name}"}

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": json.dumps(result, ensure_ascii=False),
                })

        return f"⚠️ 达到最大轮数 ({self.max_turns})，Agent 停止。"

    # ==========================================
    # 交互模式
    # ==========================================

    def chat(self):
        """交互式对话"""
        print("=" * 50)
        if self._use_mock:
            print("🤖 MyAgent（模拟模式 — 无 API key，内置智能判断）")
        else:
            print(f"🤖 MyAgent (模型: {self.model})")
        print("  输入 /quit 退出，/stats 看统计，/tools 看工具列表")
        print("=" * 50)

        while True:
            try:
                user_input = input("\n👤 ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if not user_input:
                continue
            if user_input.lower() in ("/quit", "/exit", "/q"):
                break
            if user_input == "/stats":
                stats = self.get_stats()
                print(f"\n📊 统计: {stats}")
                continue
            if user_input == "/tools":
                print(f"\n📦 可用工具 ({len(self.tools)} 个):")
                for t in self.tools:
                    name = t["function"]["name"]
                    desc = t["function"]["description"]
                    print(f"  🔧 {name}: {desc}")
                continue
            if user_input == "/reset":
                self.reset_stats()
                print("\n🔄 统计已重置")
                continue

            result = self.run(user_input)
            print(f"\n🤖 {result}")


# ==========================================
# 测试
# ==========================================

def run_demo():
    """运行所有测试"""
    print("=" * 50)
    print("🧪 MyAgent 演示模式")
    print("=" * 50)

    tests = [
        ("你好，你是谁？", "基础对话"),
        ("1024 * 768 等于多少？", "数学计算"),
        ("北京天气怎么样？", "天气查询"),
        ("现在几点了？", "时间查询"),
        ("搜索 Python 编程语言", "网络搜索"),
    ]

    agent = MyAgent()
    passed = 0

    for query, desc in tests:
        print(f"\n📝 测试: {desc}")
        print(f"  输入: {query}")
        try:
            result = agent.run(query)
            print(f"  输出: {result[:100]}...")
            assert len(result) > 0
            passed += 1
            print(f"  ✅ 通过")
        except Exception as e:
            print(f"  ❌ 失败: {e}")

    # 测试笔记记忆
    print(f"\n📝 测试: 笔记记忆")
    agent.run("记住我最喜欢的颜色是蓝色")
    result = agent.run("我喜欢什么颜色？")
    print(f"  输出: {result[:100]}...")
    if "蓝" in result:
        passed += 1
        print(f"  ✅ 通过")
    else:
        print(f"  ❌ 记忆未召回")

    stats = agent.get_stats()
    print(f"\n{'='*50}")
    print(f"📊 统计: {stats}")
    print(f"✅ {passed}/6 测试通过")
    print(f"{'='*50}")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        run_demo()
    else:
        MyAgent().chat()
