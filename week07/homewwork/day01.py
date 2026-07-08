from langchain.agents import create_agent
from langchain.tools import tool

# 10 个工具，描述故意写得有些重叠，增加选错概率
@tool
def search_routes(region: str, days: int) -> str:
    """检索徒步路线。当用户要找路线时使用。"""
    return f"{region}路线：A/B/C"

@tool
def get_weather(city: str) -> str:
    """查询天气。当用户问天气时使用。"""
    return f"{city}：晴25°C"

@tool
def generate_gear(difficulty: str, weather: str) -> str:
    """生成装备清单。根据难度和天气。"""
    return "装备：登山鞋/雨衣"

@tool
def plan_schedule(start: str, end: str) -> str:
    """安排行程时间表。"""
    return f"{start}-{end}行程表"

@tool
def navigate(from_loc: str, to_loc: str) -> str:
    """导航到目的地。"""
    return f"{from_loc}→{to_loc}路线"


# 再定义 5 个工具：translate / take_note / get_altitude / book_lodging / emergency_call
# （结构相同，每个都是 @tool + 简单函数 + mock 返回，此处省略重复代码）
all_tools = [search_routes, get_weather, generate_gear, plan_schedule, navigate,
             # translate, take_note, get_altitude, book_lodging, emergency_call
             ]  # 实际实验中补齐这 5 个工具

agent = create_agent(
    model="ollama:qwen2.5:7b",
    tools=all_tools,  # 共 10 个工具
    system_prompt="你是徒步出行助手，可使用上述工具。",
)

# 测试 5 个问题，记录选对/选错
test_cases = [
    ("川西天气怎么样？", "get_weather"),
    ("帮我找川西3天路线", "search_routes"),
    ("四姑娘山海拔多少？", "get_altitude"),
    ("帮我记一下明天出发", "take_note"),
    ("把'你好'翻译成英文", "translate"),
]