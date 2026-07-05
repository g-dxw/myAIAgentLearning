from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from model import free_model
from langchain.agents import create_agent
from langchain.tools import tool, ToolRuntime
from langgraph.types import interrupt, Command

# 短期记忆
checkpointer = InMemorySaver()
# 长期记忆 
store = InMemoryStore()


@tool
def save_user_preference(runtime:ToolRuntime, preference: str) -> str:
    """
    保存用户对徒步路线的偏好（难度、类型等）。

    runtime.store 由 LangGraph 引擎自动注入。
    该数据跨会话持久，其他 thread 也能读到。
    """
    user_id = runtime.config.get("configurable", {}).get("user_id", "anonymous")

    existing = runtime.store.get(("users",), user_id)
    prefs = existing.value if existing else {}

    prefs["preference"] = preference
    runtime.store.put(("users",), user_id, prefs)
    
    return f"已保存偏好：{preference}"

@tool
def get_user_preference(runtime: ToolRuntime) -> str:
    """
    读取用户保存的徒步偏好。

    注意：这个 tool 可以在完全不同的 thread 中调用，
    但只要 store 是同一个实例，数据就能读到。
    """
    user_id = runtime.config.get("configurable", {}).get("user_id", "anonymous")
    existing = runtime.store.get(("users",), user_id)
    if existing:
        return f"你的偏好：{existing.value.get('preference', '未设置')}"
    return "还未设置偏好"

@tool
def send_confirmation_email(runtime: ToolRuntime, recipient: str, subject: str, body: str) -> str:
    """
    发送确认邮件。危险操作——发送前需人工确认。

    流程：interrupt(payload) 暂停 → 外部确认 → Command(resume=...) 恢复
    """
    payload = {
        "action": "send_email",
        "recipient": recipient,
        "subject": subject,
        "body_preview": body[:100],
        "question": f"确认向 {recipient} 发送邮件「{subject}」？",
    }
    approval = interrupt(payload)
    # 3. 根据确认结果执行或取消
    if approval == "yes":
        # 这里调真实邮件服务
        return f"邮件已发送至 {recipient}，主题：{subject}"
    else:
        return f"已取消发送邮件至 {recipient}"

@tool
def get_user_email(runtime) -> str:
    """获取当前用户的邮箱地址。"""
    # 从 store 读取用户信息
    user_id = runtime.config.get("configurable", {}).get("user_id", "anonymous")
    item = runtime.store.get(("users",), user_id)
    if item and "email" in item.value:
        return item.value["email"]
    return "user@example.com"


agent = create_agent(
    model=free_model,
    tools=[save_user_preference, get_user_preference, send_confirmation_email, get_user_email],
    checkpointer = checkpointer,
    store= store
)

# configA = {
#     "configurable": {
#         "thread_id": "session-002",
#         "user_id": "user_123"
#     }
# }

# result = agent.invoke(
#     {
#         "messages": [{
#             "role": "user", "content": "我喜欢高等难度的徒步路线"
#         }]
#     },
#     config=configA
# )

# print(result["messages"][-1].content)
# # 4. 线程 B：同一用户换了个会话，Agent 还记得偏好
# configB = {"configurable": {"thread_id": "session-003", "user_id": "user_123"}}
# result = agent.invoke(  {
#         "messages": [{
#             "role": "user",  "content": "帮我看看我的偏好是什么"
#         }]
#     },
#     config=configB)
# print(result["messages"][-1].content)



config = {"configurable": {"thread_id": "email-001", "user_id": "user_123"}}

# try:
#     result = agent.invoke({
#         "messages": [{
#             "role": "user",  "content": "给 alice@example.com 发一封邮件，主题是周末徒步计划，内容是：明天早点到我们小区"
#         }]
#     }, config= config)

# except Exception:
#     pass

# snapshot = agent.get_state(config)

# print("next:", snapshot.next)            # ('tools',) — 说明卡在 tools 节点
# print("interrupted:", hasattr(snapshot, "interrupted") and snapshot.interrupted)

# # 第三步：人工确认，用 Command(resume=...) 恢复
# result = agent.invoke(
#     Command(resume="yes"),    # ← 关键：value "yes" 成为 interrupt() 的返回值
#     config=config,
# )
# print(result["messages"][-1].content)   # 邮件已发送至 alice@example.com，...

stream = agent.stream_events({
        "messages": [{
            "role": "user",  "content": "给 alice@example.com 发一封邮件，主题是周末徒步计划，内容是：明天早点到我们小区"
        }]
    }, config= config, version="v3")


if stream.interrupted:
    print("Agent 执行被中断")
    for interrupt_payload in stream.interrupts:
        print("中断原因:", interrupt_payload)
    print("中断时状态:", stream.output)

stream = agent.stream_events(
    Command(resume=True),
    config,
    version='v3'
)

