# Day 03 — FastAPI 路由 + 请求参数校验

## 学习目标

从零搭建一个 FastAPI 项目，掌握路由定义、Path/Query/Body 三种参数获取方式，结合 Pydantic v2 做请求校验和响应模型。为后续构建 Agent API 服务打下基础。

---

## 一、FastAPI 是什么？为什么 Agent 开发需要它？

```python
# 一个完整可用的 FastAPI 服务（只有 5 行）
from fastapi import FastAPI

app = FastAPI(title="My Agent API")

@app.get("/")
async def root():
    return {"message": "Hello Agent"}
```

启动：`uvicorn main:app --reload` → 访问 `http://127.0.0.1:8000`

**FastAPI 在 Agent 项目中的 3 个核心用途：**

| 用途 | 说明 |
|------|------|
| Agent API 服务 | 把 Agent 逻辑封装成 HTTP 接口，前端/小程序调用 |
| 工具服务 | Agent 调用的外部工具（查天气、搜路线）暴露为 API |
| 管理后台 | Agent 配置、对话历史、Token 统计的 CRUD 接口 |

> 对比你熟悉的 Node.js：FastAPI ≈ Express.js + 内置参数校验 + 自动生成 OpenAPI 文档

---

## 二、路由基础 — 对比 Express.js

### 2.1 装饰器路由 vs 链式路由

```typescript
// TS/JS — Express.js
const express = require("express");
const app = express();

app.get("/users", async (req, res) => {
  res.json({ users: [...] });
});

app.post("/users", async (req, res) => {
  const body = req.body;
  // ... 手动校验 body
});
```

```python
# Python — FastAPI
from fastapi import FastAPI

app = FastAPI()

@app.get("/users")
async def list_users():
    return {"users": [...]}

@app.post("/users")
async def create_user(name: str, age: int):  # 参数直接声明类型！
    return {"name": name, "age": age}
```

**关键差异对比：**

| 概念 | Express.js | FastAPI |
|------|-----------|---------|
| 路由定义 | `app.get(path, handler)` | `@app.get(path)` 装饰器 + `async def` |
| 请求对象 | `req.params`, `req.query`, `req.body` | **函数参数直接声明**，类型自动推断 |
| 参数校验 | 手动 + Joi/Zod | **内置 Pydantic**，自动校验+文档 |
| 返回 | `res.json(...)` | 直接 `return dict/Pydantic`，自动 JSON |
| 异步 | `async (req, res) =>` (可选) | `async def` 是推荐写法 |

### 2.2 HTTP 方法映射

```python
@app.get("/resource")      # GET — 查询
@app.post("/resource")     # POST — 创建
@app.put("/resource/{id}") # PUT — 全量更新
@app.patch("/resource/{id}") # PATCH — 部分更新
@app.delete("/resource/{id}") # DELETE — 删除
```

> 和 Express.js 一模一样，只是函数名小写。

### 2.3 路径前缀 + 路由分组

```typescript
// Express.js
const router = express.Router();
router.get("/agents", ...);
router.post("/agents", ...);
app.use("/api/v1", router);
```

```python
# FastAPI — APIRouter
from fastapi import APIRouter

router = APIRouter(prefix="/api/v1", tags=["Agent"])

@router.get("/agents")
async def list_agents(): ...

@router.post("/agents")
async def create_agent(): ...

# 在主 app 中注册
app.include_router(router)
```

> `APIRouter` ≈ Express.js 的 `Router()`，`tags` 参数会自动在 Swagger 文档中分组显示。

---

## 三、三种参数获取方式

### 3.1 Path 参数 — `{id}` 路径变量

```typescript
// Express.js
app.get("/agents/:id", async (req, res) => {
  const id = req.params.id;
  // id 是 string，需要手动 parseInt
});
```

```python
# FastAPI — 直接在路径里声明参数
from fastapi import FastAPI

app = FastAPI()

@app.get("/agents/{agent_id}")
async def get_agent(agent_id: int):  # 声明 int → 自动类型转换+校验
    return {"agent_id": agent_id, "name": f"Agent-{agent_id}"}

# /agents/abc → HTTP 422: agent_id 不是合法整数
# /agents/42  → {"agent_id": 42, "name": "Agent-42"}
```

**Path 参数的关键特性：**
- 声明类型 → 自动校验（`int` → 自动 parse + 校验合法性）
- 路径参数**必须**在 URL 路径中，不能缺省
- 多个路径参数：

```python
@app.get("/users/{user_id}/conversations/{conv_id}")
async def get_conversation(user_id: int, conv_id: str):
    return {"user_id": user_id, "conversation_id": conv_id}

# GET /users/123/conversations/conv_abc
# → {"user_id": 123, "conversation_id": "conv_abc"}
```

### 3.2 Query 参数 — `?key=value`

```typescript
// Express.js
app.get("/agents", async (req, res) => {
  const { status, page, limit } = req.query;
  // 全是 string，需要手动转型 + 默认值
  const pageNum = parseInt(page || "1");
  const limitNum = parseInt(limit || "10");
});
```

```python
# FastAPI — 函数参数默认值 = Query 参数
@app.get("/agents")
async def list_agents(
    status: str | None = None,   # 可选查询参数
    page: int = 1,               # 有默认值 = 可选
    limit: int = 10,
):
    return {
        "status": status,
        "page": page,
        "limit": limit,
        "agents": [],  # 实际查询逻辑
    }

# GET /agents?status=active&page=2&limit=20
# → {"status": "active", "page": 2, "limit": 20, "agents": []}

# GET /agents
# → {"status": None, "page": 1, "limit": 10, "agents": []}
```

**Path 和 Query 的判别规则：**

| 声明方式 | 参数来源 | 判定逻辑 |
|----------|---------|----------|
| 路径中的 `{name}` | Path | 必须出现在 URL 路径里 |
| 函数参数 | Query | 不在路径中 → 自动视为 Query 参数 |

```python
# 混合使用
@app.get("/agents/{agent_id}/messages")
async def get_messages(
    agent_id: int,                     # Path
    limit: int = 50,                   # Query
    offset: int = 0,                   # Query
    search: str | None = None,         # Query（可选）
):
    return {
        "agent_id": agent_id,
        "limit": limit,
        "offset": offset,
        "search": search,
    }

# GET /agents/42/messages?limit=20&search=hello
# → {"agent_id": 42, "limit": 20, "offset": 0, "search": "hello"}
```

### 3.3 显式 Path/Query 装饰器

当需要更精细控制时，可以用 `Path` 和 `Query` 装饰器：

```python
from fastapi import Path, Query

@app.get("/agents/{agent_id}")
async def get_agent(
    agent_id: int = Path(ge=1, description="Agent ID，从 1 开始"),  # ≥1
    include_stats: bool = Query(default=False, description="是否包含统计信息"),
):

# GET /agents/0 → HTTP 422: agent_id ≥ 1
# GET /agents/1?include_stats=true → 正常
```

**`Path` 和 `Query` 常用参数：**

| 参数 | 作用 | 示例 |
|------|------|------|
| `ge`/`le` | ≥/≤ 数值约束 | `ge=1` |
| `gt`/`lt` | >/< 数值约束 | `gt=0` |
| `min_length`/`max_length` | 字符串长度 | `min_length=3` |
| `pattern` | 正则匹配 | `pattern=r"^agent_\d+$"` |
| `default` | 默认值 | `default="active"` |
| `description` | API 文档说明 | `description="筛选状态"` |
| `alias` | 参数别名（前端传 snake_case 怎么办） | `alias="searchQuery"` |

---

## 四、Request Body — Pydantic 模型

### 4.1 基本 body 声明

```typescript
// Express.js — 需要手动解析和校验
app.post("/agents", async (req, res) => {
  const { name, model, system_prompt, max_tokens } = req.body;
  if (!name) return res.status(400).json({ error: "name is required" });
  if (max_tokens > 32000) return res.status(400).json({ error: "max_tokens too large" });
  // ...
});
```

```python
# FastAPI — Pydantic 模型自动校验
from pydantic import BaseModel, Field

class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    model: str = Field(default="claude-sonnet-4-6")
    system_prompt: str | None = None
    max_tokens: int = Field(default=4096, ge=1, le=32000)

@app.post("/agents")
async def create_agent(agent: AgentCreate):  # ← 直接声明为 Pydantic 模型
    # agent 已经校验过：name 不为空、max_tokens 在范围内
    return {
        "id": 42,
        "name": agent.name,
        "model": agent.model,
        "created": True,
    }
```

**核心优势：**
- ❌ 不需要手动 `if not name: raise` — Field 约束自动校验
- ❌ 不需要手动 JSON parse — FastAPI 自动从 request body 解析
- ✅ 自动生成 OpenAPI/Swagger 文档
- ✅ GET 请求的 Query 参数和 POST 请求的 Body 用同一套逻辑

### 4.2 嵌套模型

```python
from pydantic import BaseModel, Field
from typing import Literal

class ToolDefinition(BaseModel):
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    parameters: dict  # JSON Schema 格式

class AgentConfig(BaseModel):
    name: str
    model: str
    tools: list[ToolDefinition] = []  # 嵌套模型列表
    max_turns: int = Field(default=10, ge=1, le=100)

@app.post("/agents/config")
async def create_agent_config(config: AgentConfig):
    tool_names = [t.name for t in config.tools]
    return {
        "agent_name": config.name,
        "configured_tools": tool_names,
        "max_turns": config.max_turns,
    }

# 请求 body：
# {
#   "name": "助手小克",
#   "model": "claude-sonnet-4-6",
#   "tools": [
#     {"name": "get_weather", "description": "查天气", "parameters": {"type": "object", "properties": {}}},
#     {"name": "search", "description": "搜资料", "parameters": {"type": "object", "properties": {}}}
#   ],
#   "max_turns": 20
# }
```

### 4.3 响应模型 — 自动过滤和文档

```python
from pydantic import BaseModel, Field
from datetime import datetime

class AgentResponse(BaseModel):
    """返回给客户端的 Agent 信息（不含敏感字段）"""
    id: int
    name: str
    model: str
    created_at: datetime
    # 特意不包含 api_key、internal_notes 等敏感字段

class AgentDB(AgentResponse):
    """数据库内完整信息（含敏感字段）"""
    api_key: str
    internal_notes: str

@app.post("/agents", response_model=AgentResponse)
async def create_agent(agent_data: AgentCreate) -> AgentResponse:
    """创建 Agent — 返回时自动过滤掉 api_key 等敏感字段"""
    # 模拟数据库创建
    db_agent = AgentDB(
        id=42,
        name=agent_data.name,
        model=agent_data.model,
        created_at=datetime.now(),
        api_key="sk-secret-xxx",      # ← 会被 response_model 过滤掉！
        internal_notes="测试用 Agent",
    )
    # response_model=AgentResponse → 只返回 AgentResponse 里的字段
    return db_agent

# 实际返回：
# {
#   "id": 42,
#   "name": "助手小克",
#   "model": "claude-sonnet-4-6",
#   "created_at": "2026-05-14T10:30:00"
# }
# ❌ 没有 api_key，没有 internal_notes
```

**`response_model` 的威力：**
- 自动**只返回声明中的字段**（免泄露敏感数据）
- 自动进行类型转换（`datetime` → ISO 字符串）
- 自动在 Swagger 文档中显示响应结构

---

## 五、Status Code 和异常处理

### 5.1 自定义状态码

```python
from fastapi import status

@app.post("/agents", status_code=status.HTTP_201_CREATED)
async def create_agent(agent: AgentCreate):
    return {"id": 42, "name": agent.name}

@app.delete("/agents/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(agent_id: int):
    pass  # 204 不返回 body
```

### 5.2 HTTPException

```python
from fastapi import HTTPException

@app.get("/agents/{agent_id}")
async def get_agent(agent_id: int):
    agent = find_agent(agent_id)
    if agent is None:
        raise HTTPException(
            status_code=404,
            detail=f"Agent {agent_id} 未找到",
        )
    return agent
```

---

## 六、Agent 场景实战：构建一个 Agent API 端点

把 Day 01 和 Day 02 的知识串联起来，写一个**真正能调用 Claude API 的 Agent 端点**：

```python
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field
from typing import Literal
import httpx
import os

app = FastAPI(title="AI Agent API", version="0.1.0")

# ====== 数据模型 ======

class AgentMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str

class AgentRequest(BaseModel):
    messages: list[AgentMessage] = Field(min_length=1)
    model: str = Field(default="claude-sonnet-4-6")
    max_tokens: int = Field(default=4096, ge=1, le=32000)
    temperature: float = Field(default=0.7, ge=0, le=1)

class TokenUsage(BaseModel):
    input_tokens: int
    output_tokens: int

class AgentResponse(BaseModel):
    reply: str
    model: str
    usage: TokenUsage

# ====== 路由 ======

@app.post("/chat", response_model=AgentResponse)
async def chat(request: AgentRequest):
    """
    调用 LLM 的 Agent 聊天接口
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="API Key 未配置")

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": request.model,
                "max_tokens": request.max_tokens,
                "messages": [m.model_dump() for m in request.messages],
            },
        )

    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)

    data = resp.json()
    return AgentResponse(
        reply=data["content"][0]["text"],
        model=data["model"],
        usage=TokenUsage(**data["usage"]),
    )


@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "version": "0.1.0"}


# ====== 启动方式 ======
# uvicorn main:app --reload
# 然后：
# curl -X POST http://127.0.0.1:8000/chat \
#   -H "Content-Type: application/json" \
#   -d '{"messages": [{"role": "user", "content": "你好！"}]}'
```

---

## 七、今日练习（约 2.5 小时）

### 练习 1：搭建基础路由（20 min）

1. 创建 `main.py`，写一个 FastAPI 应用
2. 实现以下路由：
   - `GET /` → 返回 `{"message": "Agent API is running"}`
   - `GET /agents` → 返回一个静态 Agent 列表
   - `GET /agents/{agent_id}` → 返回单个 Agent（用 Path 校验 `agent_id ≥ 1`）

### 练习 2：Query 参数筛选（20 min）

给练习 1 的 `GET /agents` 添加筛选参数：
- `status: str | None = None` — 按状态筛选
- `page: int = 1` — 分页页码
- `limit: int = 10` — 每页数量

返回时包含 `total` 和 `page` 信息。

### 练习 3：POST + Body 校验（30 min）

创建 `POST /agents` 路由，用 Pydantic 模型做请求校验：

```python
class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    description: str | None = None
    model: str = Field(default="claude-sonnet-4-6")
```

校验规则：
- `name` 不能为空，最长 50 字符
- `model` 只能是常见的 Claude 模型名（用 Literal 或 pattern 约束）

### 练习 4：Response Model 练习（20 min）

1. 定义 `AgentResponse` 模型（不含 `api_key` 等敏感字段）
2. 定义 `AgentDetail` 模型（包含所有字段）
3. `POST` 返回 `AgentResponse`，`GET /agents/{id}/detail` 返回 `AgentDetail`

### 练习 5：综合实战 — Agent 配置 API（60 min）

实现一个完整的 Agent 配置管理 API：

```python
# 数据模型
class ToolConfig(BaseModel):
    name: str
    description: str
    parameters: dict  # JSON Schema

class AgentConfig(BaseModel):
    name: str
    system_prompt: str = Field(min_length=10, description="系统提示词，至少 10 字")
    model: str = "claude-sonnet-4-6"
    tools: list[ToolConfig] = Field(default=[], max_length=10)
    max_turns: int = Field(default=10, ge=1, le=50)

# 路由
# POST /agents — 创建配置（返回 201）
# GET /agents — 列出所有配置（支持 name 模糊搜索）
# GET /agents/{id} — 查看单个配置
# DELETE /agents/{id} — 删除（返回 204）

# 数据用全局 list 暂存（后续学到数据库再换）
agents_db: list[dict] = []
```

---

## 八、踩坑记录

```python
# 写代码时记录你遇到的所有坑：

# [ ] 坑 1：____________________
# 解决：____________________

# [ ] 坑 2：____________________
# 解决：____________________
```

**常见坑（提前预警）：**

| 坑 | 表现 | 解决 |
|----|------|------|
| ❌ 忘记安装 `uvicorn` | `ModuleNotFoundError: No module named 'uvicorn'` | `pip install "uvicorn[standard]"` |
| ❌ `async def` 写成 `def` | 路由能跑但不支持异步 | 默认用 `async def` |
| ❌ Pydantic Field 约束写错 | 能通过但奇怪行为 | 检查 `ge`/`le` 是否正确 |
| ❌ 路由顺序 | `/agents/{id}` 和 `/agents/search` 冲突 | 具体路由放前面，路径参数放后面 |
| ❌ `response_model` 忘写 | 敏感字段可能泄露 | 始终给响应加上 Pydantic 模型 |
| ❌ Body 用 GET | FastAPI 的标准用法不支持 GET + body | 查询用 Query 参数 |

---

## 九、Day 03 检查清单

- [ ] 能创建 FastAPI 项目并用 `uvicorn` 启动
- [ ] 能定义 `@app.get` / `@app.post` / `@app.put` / `@app.delete` 路由
- [ ] 能使用 `{agent_id}` 路径参数
- [ ] 能用函数参数默认值接收 Query 参数
- [ ] 能用 Pydantic `BaseModel` 做请求 Body 校验
- [ ] 能使用 `Path()` / `Query()` 添加约束（ge/le/min_length）
- [ ] 能使用 `response_model` 控制返回字段
- [ ] 能使用 `HTTPException` 返回错误
- [ ] 能使用 `APIRouter` 做路由分组
- [ ] 能理解 FastAPI 路由和 Express.js 路由的对照关系

## 明天计划

- [ ] Day 04 — FastAPI 依赖注入 + 错误处理（Depends、中间件、全局异常处理）
