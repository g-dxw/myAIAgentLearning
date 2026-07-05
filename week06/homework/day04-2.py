from typing import Annotated, TypedDict
import operator
from langchain.tools import tool
from langchain.messages import AnyMessage, ToolMessage
from langgraph.graph import StateGraph, END, START
from model import free_model

# ─── 1. 工具定义（复用 Day 02 的三个工具）──────────────────────
@tool
def get_weather(city: str) -> str:
    """查询指定城市的当前天气。city 为城市名，如 '北京'、'上海'。"""
    db = {"北京": "晴 25°C", "上海": "多云 28°C", "Tokyo": "小雨 18°C"}
    return db.get(city, f"{city}：暂无天气数据")


@tool
def search_routes(location: str, difficulty: str = "easy") -> str:
    """根据地点检索徒步路线。location 为起点城市，difficulty 为难度 easy/medium/hard。"""
    routes = {"北京": "香山、百望山、奥森", "杭州": "北高峰、宝石山"}
    return f"为 {location}({difficulty}) 找到：{routes.get(location, '暂无路线')}"


@tool
def calculate_distance(start: str, end: str) -> str:
    """计算两个地点之间的直线距离（公里）。start/end 为地点名。"""
    table = {("北京", "上海"): 1213, ("杭州", "上海"): 175}
    d = table.get((start, end)) or table.get((end, start))
    return f"{start}→{end} 约 {d} 公里" if d else f"暂无 {start}↔{end} 距离数据"


tools = [get_weather, search_routes, calculate_distance]
tool_map = {tool.name: tool for tool in tools}

class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], operator.add]


def call_model(state: AgentState) -> dict:
   """Agent 节点：将消息传给绑了工具的 LLM，返回 AIMessage（可能含 tool_calls）。

    这是循环中的"思考"环节——LLM 看当前消息历史，决定是直接回答还是调工具。
    """
   respons = free_model.bind_tools(tools).invoke(state["messages"])
   return {"messages": [respons]}


def execute_tools(state: AgentState) -> dict:

    last_msg = state["messages"][-1]

    tool_messages = []

    for tc in last_msg.tool_calls:
        tool_name = tc["name"]
        tool_args = tc["args"]
        tool_call_id = tc["id"]

        tool_fn = tool_map.get(tool_name);
        if tool_fn is None:
            result = f"错误：未知工具 '{tool_name}'"
        else:
            try:
                result = tool_fn.invoke(tool_args)
            except Exception as e:
                result = f"工具执行异常：{e}"

        tool_msg = ToolMessage(content= str(result), tool_call_id = tool_call_id)
        tool_messages.append(tool_msg)

    return {"messages": tool_messages}

def should_continue(state: AgentState) -> str:
    last_msg = state['messages'][-1]
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        return "tools"
    return END

def build_agent_graph()-> StateGraph:
    graph = StateGraph(AgentState)

    graph.add_node("agent", call_model)
    graph.add_node("tools", execute_tools)

    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})

    graph.add_edge("tools", "agent")

    return graph.compile()


# ─── 调用 ───
if __name__ == "__main__":
    from langchain_core.messages import HumanMessage

    app = build_agent_graph()

    result = app.invoke({
        "messages": [
            HumanMessage(content="北京天气如何？再算一下北京到上海的距离"),
        ],
    })

    print("=" * 50)
    print("手写 StateGraph Agent 运行结果：")
    print("最终回复:", result["messages"][-1].content)
    print(f"共产生 {len(result['messages'])} 条消息")
    for i, msg in enumerate(result["messages"]):
        print(f"  [{i}] {msg.__class__.__name__}: {msg.content[:60]}...")

