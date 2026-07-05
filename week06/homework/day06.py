from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from model import free_model

@tool
def get_weather(city: str) -> str:
    """查询指定城市的当前天气。"""
    # 模拟天气查询
    data = {"北京": "晴 22°C", "成都": "多云 28°C", "上海": "小雨 19°C"}
    return data.get(city, f"{city}：气温 20°C，天气未知")


@tool
def get_temperature(city: str) -> str:
    """查询指定城市的当前温度。"""
    data = {"北京": "22°C", "成都": "28°C", "上海": "19°C"}
    return data.get(city, "20°C")


agent = create_agent(
    model=free_model,
    tools=[get_weather, get_temperature],
    system_prompt="你是天气助手，负责查询天气。",
    checkpointer=InMemorySaver(),
)

config = {"configurable": {"thread_id": "stream-demo-001"}}

input_data = {
    "messages": [{"role": "user", "content": "北京今天天气怎么样？温度多少？"}]
}

stream = agent.stream_events(input_data, config, version="v3")

# # — 消费所有事件类型 —
# for idx, snapshot in enumerate(stream):
#     print(f"\n=== 帧 {idx + 1} ===")

#     print(snapshot.get('data'))
#     # 1) messages：逐 token 流式文本
#     if snapshot.get('data').messages:
#         for msg in snapshot.messages:
#             if msg.content:
#                 print(f"[token]: {msg.content}")

#     # 2) values：节点级状态快照
#     if snapshot.values:
#         top_keys = list(snapshot.values.keys())
#         print(f"[state]: keys={top_keys}")

#     # 3) interrupts：中断信息
#     if snapshot.interrupted:
#         print(f"[interrupt]: {snapshot.interrupts}")

# 最终输出
final_output = stream.output
if final_output:
    last_msg = final_output["messages"][-1]
    print(f"\n最终回答: {last_msg.content}")