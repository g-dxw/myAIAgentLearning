"""
## 统一响应格式

```json
// 成功
{"success": true, "data": {...}, "meta": {"page": 1, "total": 10}}

// 失败
{"success": false, "error": "描述", "data": null}
```
"""
from typing import Generic, TypeVar, Optional

from pydantic import BaseModel, Field

T = TypeVar("T")

class APIResponse(BaseModel, Generic[T]):
    success: bool = Field(default=True, description="请求是否成功")
    data: Optional[T] = Field(None, description="响应数据")
    error: Optional[str] = Field(None, description="错误信息，成功时为 null")
    meta: Optional[dict] = Field(None, description="可选的元信息")
