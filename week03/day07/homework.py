"""
===== MyAgent — 多工具 AI Agent =====

功能定位：
  一个不依赖任何 Agent 框架（LangChain / CrewAI / AutoGen）、
  纯手写的多工具 Agent。用 httpx 直接调 LLM API，
  手写 Agent Loop，手写工具调度。

工具列表（6 个）：
  1. get_weather     — 天气查询（模拟）
  2. calculate       — 数学计算（安全沙箱）
  3. get_current_time — 日期时间
  4. search_web      — 网络搜索（DuckDuckGo）
  5. save_note       — 保存笔记到内存知识库
  6. get_note        — 检索笔记

核心设计原则：
  - messages 是唯一的状态源，每轮只追加不修改
  - 工具执行结果用 tool 角色返回，不混入 user/assistant
  - 错误不抛异常，而是作为 tool 结果发给 LLM 自行处理
  - 所有工具都是幂等的（多次调用不产生副作用）

输出物：
  week03/day07/my_agent.py  ← 最终可运行的 Agent
"""

import json
import re
import sys
from tabnanny import verbose
import uuid
import httpx
from pydantic import BaseModel, Field, ValidationError
import datetime

class GetWeatherInput(BaseModel):
    location: str = Field(description="要查询的地点")
    date: str = Field(default_factory=lambda: datetime.date.today().isoformat(),  description="查询的日期，格式为 YYYY-MM-DD")

class CalculateInput(BaseModel):
    expression: str = Field(description="执行数学计算。支持加减乘除、括号、幂运算。例如：1024 * 768, (15+25)*2, 2**10")

class SearchWebInput(BaseModel):
    query: str = Field(..., description="要搜索的查询内容")
    max_results: int = Field(default=5, description="返回的搜索结果数量限制，默认5条")

class SaveNoteInput(BaseModel):
    note: str = Field(description="要保存的笔记内容")
    tags: list[str] = Field(default_factory=list, description="笔记标签")
    title: str = Field(..., description="笔记标题")
    author: str = Field(..., description="笔记作者")
    created_at: str = Field(default_factory=lambda: datetime.datetime.now().isoformat(), description="笔记创建时间")

class GetNoteInput(BaseModel):
    note_id: str = Field(..., description="要检索的笔记 ID")

# 无参工具模型（规范函数调用 schema）
class EmptyInput(BaseModel):
    pass

class MyAgent:
    def __init__(
            self, 
            model: str = "deepseek-v4-flash",
            api_key: str = "sk-9506bf127cba419aba3ee0a9db118a7a",
            base_url: str = "https://api.deepseek.com",
            max_turns: int = 15
        ):

        self.model = model
        print(f"Initializing MyAgent with model: {model}")
        self.api_key = api_key
        self.base_url = base_url
        self.max_turns = max_turns

        # 工具相关
        self.tools: list[dict] = []
        self.handlers: dict[str, callable] = {}
        self._register_default_tools()

        # 笔记相关
        self.notes: dict[str, dict] = {}
        # 系统提示词
        self.system_prompt = """你是一个强大的AI，你可以结合工具为用户进行解答，用中文回答。"""

        # 工具循环检查
        self._last_tool_calls: list[tuple[str,str]] = []


        self.reset_stats()

    def reset_stats(self):
        self.total_turns = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.tool_call_count = 0

    def get_stats(self) -> dict:
        return {
            "total_turns": self.total_turns,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "tool_call_count": self.tool_call_count
        }   

    # ==========================================
    # 工具注册
    # ==========================================
    def register_tool(self, tool_info: dict, handler: callable):
        """注册一个新工具"""
        self.tools.append({
            "type": "function",
            "function": tool_info
        })
        self.handlers[tool_info["name"]] = handler

    def _register_default_tools(self):
        """注册默认工具"""
        self.register_tool({
            "name": "get_weather",
            "description": "获取天气信息",
            "parameters": GetWeatherInput.model_json_schema()
        }, self.get_weather)
        self.register_tool({
            "name": "calculate",
            "description": "数学计算",
            "parameters": CalculateInput.model_json_schema()        
        }, self.calculate)
        self.register_tool({
            "name": "get_current_time",
            "description": "获取当前时间",
            "parameters": EmptyInput.model_json_schema()
        }, self.get_current_time)
        self.register_tool({
            "name": "search_web",
            "description": "网络搜索",
            "parameters": SearchWebInput.model_json_schema()
        }, self.search_web)
        self.register_tool({
            "name": "save_note",
            "description": "保存笔记",
            "parameters": SaveNoteInput.model_json_schema()
        }, self.save_note)
        self.register_tool({
            "name": "get_note",
            "description": "获取笔记",
            "parameters": GetNoteInput.model_json_schema()
        }, self.get_note)


    def get_weather(self, params: dict) -> dict:
        try:
            args = GetWeatherInput(**params)
        except ValidationError as e:
            return {"error": f"参数校验失败: {e.errors()}"}
        return {
            "location": args.location,
            "date": args.date,
            "weather": "晴天",
            "temperature": "25°C"
        }

    def calculate(self, params: dict) -> dict:
        try:
            args = CalculateInput(**params)
        except ValidationError as e:
            return {"error": f"参数校验失败: {e.errors()}"}

        allowed = set("0123456789+-*/.()% ")
        if not all(c in allowed for c in args.expression):
            return {"error": "表达式包含非法字符", "expression": args.expression}
        if re.search(r'__|[a-zA-Z]', args.expression):
            return {"error": "不允使用字母", "expression": args.expression}
        try:
            result = eval(args.expression)  # 教学演示，生产用 numexpr
            return {"expression": args.expression, "result": result}
        except Exception as e:
            return {"error": f"计算错误: {e}", "expression": args.expression}

    def get_current_time(self, params: dict) -> dict:
        try:
            EmptyInput(**params)
        except ValidationError as e:
            return {"error": f"参数校验失败: {e.errors()}"}
        now = datetime.datetime.now()
        return {
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M:%S"),
            "weekday": ["周一","周二","周三","周四","周五","周六","周日"][now.weekday()],
            "current_time": now.isoformat()
        }

    def search_web(self, params: dict) -> dict:
        """搜索互联网（DuckDuckGo）"""
        try:
            args = SearchWebInput(**params)
        except ValidationError as e:
            return {"error": f"参数校验失败: {e.errors()}"}
        try:
            import httpx
            resp = httpx.get(
                "https://html.duckduckgo.com/html/",
                params={"q": args.query},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10,
            )
            results = []
            for item in resp.text.split('<a rel="nofollow" href="')[1:args.max_results+1]:
                url = item.split('"')[0]
                title_match = re.search(r'class="result__title".*?>(.*?)</a>', item, re.DOTALL)
                snippet_match = re.search(r'class="result__snippet".*?>(.*?)</', item, re.DOTALL)
                title = re.sub(r'<[^>]+>', '', title_match.group(1)) if title_match else url
                snippet = re.sub(r'<[^>]+>', '', snippet_match.group(1)) if snippet_match else ""
                results.append({"title": title.strip(), "url": url, "snippet": snippet.strip()})
            return {"query": args.query, "results": results, "total": len(results)}
        except Exception as e:
            return {"query": args.query, "results": [], "error": str(e)}

    def save_note(self, params: dict) -> dict:
        try:
            args = SaveNoteInput(**params)
        except ValidationError as e:
            return {"error": f"参数校验失败: {e.errors()}"}
        note_id = str(uuid.uuid4())
        created_at = args.created_at
        self.notes[note_id] = {
            "title": args.title,
            "note": args.note,
            "author": args.author,
            "note_id": note_id,
            "created_at": created_at,
            "tags": args.tags
        }
        return {
            "note_id": note_id,
            "message": "Note saved successfully."
        }

    def get_note(self, params: dict) -> dict:
        try:
            args = GetNoteInput(**params)
        except ValidationError as e:
            return {"error": f"参数校验失败: {e.errors()}"}
        note = self.notes.get(args.note_id)
        if note:
            return {
                "found": True,
                "value": note,
                "message": "Note found successfully."
            }
        return {
            "found": False,
            "message": "Note not found."
        }


    def _call_llm(self, messages: list[dict]) -> dict:
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
            "stream": False,
        }
        try:
            with httpx.Client(timeout=120) as client:
                print(f"  🧠 调用模型，消息长度: {len(messages)}，工具数量: {len(self.tools)}")
                print(self.api_key, self.base_url)
                resp = client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers, 
                    json=body,
                )
                resp.raise_for_status()
                data = resp.json()
                if "usage" in data:
                    self.total_input_tokens += data["usage"].get("prompt_tokens", 0)
                    self.total_output_tokens += data["usage"].get("completion_tokens", 0)
                return data
        except Exception as e:
            return {"error": f"LLM 请求异常: {str(e)}"}


    def _detect_tool_loop(self, tool_calls: list[dict]) -> bool:
        """
        检测 LLM 是否陷入工具循环。

        如果连续两轮调用完全相同的工具+参数，判定为循环。
        """
        print(f"  🔄 检测工具循环，当前调用: {[(tc['function']['name'], tc['function']['arguments']) for tc in tool_calls]}")
        current = sorted([
            (tc["function"]["name"], tc["function"]["arguments"])
            for tc in tool_calls
        ])

        if self._last_tool_calls and current == self._last_tool_calls:
            return True
        self._last_tool_calls = current
        return False
    
    def run(self, user_input: str) -> str:
        """
        主入口：接受用户输入，返回 Agent 回答。
        """
        messages = [{
            "role": "system",
            "content": self.system_prompt
        }, {
            "role": "user", 
            "content": user_input
        }]
        
        self._last_tool_calls = []

        for turn in range(self.max_turns):
            self.total_turns += 1
            loop_count = 0

            response = self._call_llm(messages)
            if "error" in response:
                return f"LLM 调用失败：{response['error']}"
            assistant_msg = response["choices"][0]["message"]

            if not assistant_msg.get("tool_calls"):
                final_text = assistant_msg.get("content", "") or ""
                return final_text
            
            print(f"  🧾 模型调用了 {len(assistant_msg['tool_calls'])} 个工具")
            if self._detect_tool_loop(assistant_msg["tool_calls"]):
                return "检测到工具循环，已终止。"
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
                        print(f"调用工具{handler}, {func_name}，参数: {func_args}")
                        result = handler(params=func_args)
                    except Exception as e:
                        result = {"error": f"工具执行失败: {e}"}
                else:
                    result = {"error": f"未知工具: {func_name}"}

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": json.dumps(result, ensure_ascii=False),
                })
                print(f"{messages}")
                
        return f"⚠️ 达到最大轮数 ({self.max_turns})，Agent 停止。"
    
    def chat(self):
        """交互式对话"""
        print("=" * 50)
        print(f"🤖 MyAgent (模型: {self.model})")
        print("  输入 /quit 退出，/stats 看统计，/tools 看工具列表")
        print("=" * 50)

        while True:
            try:
                user_input = input("用户输入: ")
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if user_input.lower() in ("/quit", "/exit", "/q"):
                break
            elif user_input == "/stats":
                stats = self.get_stats()
                print(f"\n📊 统计: {stats}")
                continue
            elif user_input == "/tools":
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
            else:
                response = self.run(user_input)
                print(f"Agent 回复: {response}")


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