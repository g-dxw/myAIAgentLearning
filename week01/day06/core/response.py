from pydantic import BaseModel, Field
from typing import Generic, TypeVar

T = TypeVar("T")

class APIResponse(BaseModel, Generic[T]):
    success: bool = Field(default=True, description="请求是否成功")
    data: T | None = Field(None, description="响应数据")
    error: str | None = Field(None, description="错误信息，成功时为 null")
    meta: dict | None = Field(None, description="可选的元信息")

class PaginatedResponse(BaseModel):
    total: int = Field(..., description="总记录数")
    page: int = Field(..., description="当前页码")
    page_size: int = Field(..., description="每页记录数")
    total_pages: int = Field(..., description="总页数")

