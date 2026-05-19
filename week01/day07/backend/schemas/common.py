from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    code: int = 200
    message: str = "success"
    data: T | None = None


class PageResult(BaseModel, Generic[T]):
    code: int = 200
    message: str = "success"
    data: list[T] = []
    total: int = 0
    page: int = 1
    pageSize: int = 20


class PageParams(BaseModel):
    page: int = 1
    pageSize: int = 20
