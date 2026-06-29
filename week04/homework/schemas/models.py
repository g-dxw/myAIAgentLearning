from typing import Optional, List
from pydantic import BaseModel, Field
from datetime import datetime


# ─── 文档相关 ───
class DocumentUploadResponse(BaseModel):
    doc_id: int
    chunk_count: int
    filename: str


class DocumentInfo(BaseModel):
    id: int
    filename: str
    file_type: str
    size_bytes: int
    chunk_count: int
    status: str = "pending"
    error_msg: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class DocumentListResponse(BaseModel):
    items: List[DocumentInfo]
    total: int


# ─── 对话相关 ───
class ConversationCreate(BaseModel):
    title: str = Field(default="新对话", min_length=1, max_length=255)


class ConversationInfo(BaseModel):
    id: int
    title: str
    created_at: datetime

    class Config:
        from_attributes = True


class MessageInfo(BaseModel):
    id: int
    conversation_id: int
    role: str
    content: str
    sources: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ─── 问答相关 ───
class QuestionRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    conversation_id: Optional[int] = None
    stream: bool = False


class SourceInfo(BaseModel):
    text: str
    metadata: dict
    similarity: float


class QAResponse(BaseModel):
    answer: str
    sources: List[SourceInfo]
    usage: Optional[dict] = None


class StreamChunk(BaseModel):
    delta: str
    done: bool = False
    sources: Optional[List[SourceInfo]] = None
