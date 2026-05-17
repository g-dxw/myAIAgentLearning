# ==========================================
# 数据模型（Pydantic）
# ==========================================
from datetime import datetime
from pydantic import BaseModel, Field, Field


class ChatRequest(BaseModel):
    conversation_id: str = Field(min_length=1, max_length=36, description="对话 ID")
    message: str = Field(min_length=1, max_length=4000, description="用户消息")
    model: str = Field(default="qwen2.5:1.5b", description="模型名称")

class ChatResponse(BaseModel):
    reply: str
    model: str
    conversation_id: str
    usage: dict


# 消息返回模型（适配你的 Message 表）
class MessageResponse(BaseModel):
    id: int
    conversation_id: str
    role: str
    content: str
    create_at: datetime