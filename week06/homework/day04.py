from typing import TypedDict, Annotated
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, START, MessagesState
from model import free_model
from langgraph.prebuilt import ToolNode, tools_condition
from langchain.agents import create_agent
from langgraph.errors import GraphRecursionError
from langchain_core.prompts import ChatPromptTemplate

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

# ─── 2. agent 节点：调模型（绑了工具）──────────────────────────
def call_model(state: MessagesState) -> dict:
    """LLM 节点：把全部历史发给模型，把回复追加到 messages。"""
    response = free_model.bind_tools(tools).invoke(state["messages"])
    return {"messages": [response]}


# ─── 3. 建图：两节点 + 条件边 + 循环边 ─────────────────────────

# graph = StateGraph(MessagesState)
# graph.add_node("agent", call_model)
# graph.add_node("tools", ToolNode(tools))

# graph.add_edge(START, "agent")
# graph.add_conditional_edges("agent", tools_condition)
# graph.add_edge("tools", "agent")

# app = graph.compile()

# # ─── 4. 调用 ──────────────────────────────────────────────────
# if __name__ == "__main__":
#     try:
#         result = app.invoke({
#             "messages": [
#                 SystemMessage(content="你是一个徒步出行助手，可查天气、检索路线、算距离。"),
#                 HumanMessage(content="我想去北京徒步，帮我查一下天气和路线。"),
#             ],
#         }, {
#             config: {
#                 "recursion_limit": 50,  # 限制循环次数，避免无限循环
#             }
#         })
#     except GraphRecursionError as e:
#         print(f"调用失败: {e}")
#         exit(1)
#     # invoke 返回最终全状态，回复在 messages 最后一条
#     print("最终回复:", result["messages"][-1].content)
#     print(f"共产生 {len(result['messages'])} 条消息")

# 1. 必须定义提示词
prompt = ChatPromptTemplate.from_messages([
    ("system", "你是一个徒步出行助手，可查天气、检索路线、算距离。"),
    ("human", "{input}"),
    ("placeholder", "{agent_scratchpad}")
])

agent  = create_agent(model=free_model, tools=tools, prompt=prompt)
agent_executor  = agent.bind_tools(tools)

result = agent.invoke([
    
    HumanMessage(content="我想去北京徒步，帮我查一下天气和路线。"),
])

print(result["messages"][-1].content)


