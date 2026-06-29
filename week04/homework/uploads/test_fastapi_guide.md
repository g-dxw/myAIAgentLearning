# FastAPI 框架完整指南

## 一、FastAPI 简介

FastAPI 是一个现代、高性能的 Python Web 框架，基于标准 Python 类型提示构建。
它由 Sebastian Ramirez 开发，于 2018 年首次发布。

FastAPI 基于两个核心库构建：
- **Starlette**：用于 Web 部分，提供异步支持和路由功能
- **Pydantic**：用于数据部分，提供数据验证和序列化

主要特点：
1. 高性能：性能可与 NodeJS 和 Go 媲美，是目前最快的 Python Web 框架之一
2. 快速开发：开发速度提升约 200% 至 300%
3. 更少的 Bug：减少约 40% 的人工错误
4. 直观易用：强大的编辑器支持，自动补全功能
5. 简洁明了：尽量减少代码重复
6. 健壮可靠：自动生成交互式文档
7. 标准化：基于并完全兼容 OpenAPI 和 JSON Schema

## 二、安装与快速入门

安装命令：
```bash
pip install fastapi uvicorn
```

第一个 FastAPI 应用：
```python
from fastapi import FastAPI

app = FastAPI()

@app.get("/")
async def root():
    return {"message": "Hello World"}
```

启动开发服务器：
```bash
uvicorn main:app --reload
```

参数说明：
- `main`：main.py 文件（模块）
- `app`：FastAPI 实例名称
- `--reload`：代码修改后自动重启（开发模式）

## 三、路由与请求方法

FastAPI 支持所有 HTTP 请求方法：GET、POST、PUT、DELETE、PATCH、HEAD、OPTIONS、TRACE。

定义路由的代码示例：
```python
# GET 请求 - 获取数据
@app.get("/items/")
async def read_items():
    return [{"item_id": "1"}, {"item_id": "2"}]

# POST 请求 - 创建数据
@app.post("/items/")
async def create_item(item: dict):
    return {"item": item}

# PUT 请求 - 更新数据
@app.put("/items/{item_id}")
async def update_item(item_id: int, item: dict):
    return {"item_id": item_id, **item}

# DELETE 请求 - 删除数据
@app.delete("/items/{item_id}")
async def delete_item(item_id: int):
    return {"deleted": item_id}
```

## 四、路径参数与查询参数

路径参数是 URL 中的一部分，用 `{}` 包围：
```python
@app.get("/items/{item_id}")
async def read_item(item_id: int, q: str = None):
    return {"item_id": item_id, "q": q}
```

查询参数是 URL 中 `?` 后面的部分：
```python
@app.get("/items/")
async def read_items(skip: int = 0, limit: int = 10):
    return {"skip": skip, "limit": limit}
```

## 五、请求体与 Pydantic 模型

使用 Pydantic BaseModel 定义请求体模型：
```python
from pydantic import BaseModel

class Item(BaseModel):
    name: str
    description: str = None
    price: float
    tax: float = 0.0

@app.post("/items/")
async def create_item(item: Item):
    item_dict = item.model_dump()
    if item.tax:
        price_with_tax = item.price + item.tax
        item_dict.update({"price_with_tax": price_with_tax})
    return item_dict
```

Pydantic 会自动进行数据验证：类型检查、必填检查、范围验证、嵌套模型支持。

## 六、依赖注入

FastAPI 的依赖注入系统是其核心特性之一，使用 `Depends` 函数实现。

简单依赖示例：
```python
from fastapi import Depends

async def common_parameters(q: str = None, skip: int = 0, limit: int = 100):
    return {"q": q, "skip": skip, "limit": limit}

@app.get("/items/")
async def read_items(commons: dict = Depends(common_parameters)):
    return commons
```

类作为依赖：
```python
class CommonQueryParams:
    def __init__(self, q: str = None, skip: int = 0, limit: int = 100):
        self.q = q
        self.skip = skip
        self.limit = limit

@app.get("/items/")
async def read_items(commons: CommonQueryParams = Depends(CommonQueryParams)):
    return {"q": commons.q, "skip": commons.skip, "limit": commons.limit}
```

子依赖：依赖可以有其他依赖，形成依赖链。FastAPI 会自动解析依赖关系图。

## 七、中间件

FastAPI 支持 Starlette 的中间件机制。

CORS 中间件（跨域资源共享）配置：
```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

自定义中间件：
```python
from fastapi import Request
import time

@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    return response
```

## 八、异步支持

FastAPI 原生支持异步编程。使用 `async def` 定义的路由处理函数会在线程池中运行。

异步数据库示例：
```python
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

engine = create_async_engine("sqlite+aiosqlite:///./db.sqlite")

async def get_db():
    async with AsyncSession(engine) as session:
        yield session
```

同步与异步函数的选择：
- 如果路由中包含异步操作（如数据库查询、HTTP 请求），使用 `async def`
- 如果路由中只有 CPU 密集型操作（如数学计算），可以使用普通 `def`

## 九、SSE 流式响应

FastAPI 支持 Server-Sent Events (SSE) 流式响应：

```python
from fastapi.responses import StreamingResponse
import json

async def event_generator():
    for i in range(10):
        data = {"index": i, "message": f"消息 {i}"}
        yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
        await asyncio.sleep(0.5)

@app.get("/stream")
async def stream_response():
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream"
    )
```

SSE 协议格式：
```
event: message
data: {"index": 0, "message": "消息 0"}
```

SSE 的优点：基于标准 HTTP 协议，无需 WebSocket；服务端单向推送；自动重连机制。

## 十、API 文档

FastAPI 自动生成交互式 API 文档，无需额外配置。

访问方式：
- **Swagger UI**：访问 http://localhost:8000/docs
- **ReDoc**：访问 http://localhost:8000/redoc

文档会根据路由、参数、Pydantic 模型和类型提示自动生成。

自定义文档信息：
```python
app = FastAPI(
    title="我的 API",
    description="这是一个示例 API",
    version="1.0.0",
    contact={"name": "API 支持", "email": "support@example.com"},
    license_info={"name": "MIT"},
)
```
