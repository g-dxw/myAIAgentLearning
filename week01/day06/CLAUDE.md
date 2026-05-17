# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述
Agent 对话管理平台 — FastAPI 后端 + 纯前端聊天 UI，支持多 Agent 对话、SSE 流式输出、语音转文字。

## 启动命令

```bash
# 启动开发服务器
uvicorn main:app --reload --port 8000

# 依赖安装（手动维护，无 requirements.txt）
pip install fastapi uvicorn sqlalchemy aiosqlite httpx sse-starlette python-multipart faster-whisper
```

后端运行在 `http://localhost:8000`，前端 `web/` 目录通过 StaticFiles 挂载，根路径直接返回 `index.html`。
LLM 依赖本地 Ollama (`localhost:11434`)，默认模型 `qwen2.5:1.5b`。

## 架构分层

```
main.py              → 应用入口，组装 routers / middlewares / exception handlers / lifespan
api/router.py        → 汇总所有子路由，统一前缀 /api/v1
api/v1/agents.py     → Agent CRUD（骨架，待实现）
api/v1/tools.py      → Tool CRUD（骨架，待实现）
api/v1/chat.py       → POST /chat/stream（sse-starlette）+ /chat/stream-legacy（手动 SSE，学习用）
api/v1/conversations.py → 对话管理 — 创建对话时调 LLM + 写库，含历史查询/删除
api/v1/uploads.py    → POST /upload/audioasr — 语音文件上传 + faster-whisper 转文字
core/database.py     → SQLAlchemy async engine + session factory + lifespan init_db
core/client.py       → httpx AsyncClient 依赖注入（base_url=localhost:11434）
core/middleware.py   → 三个中间件：计时、请求体日志、Request-ID
core/exception.py    → 全局 Exception → APIResponse 异常处理
core/response.py     → APIResponse[T] 统一响应格式
models/message.py    → Message 表（id, conversation_id, role, content, create_at）
schemas/chat.py      → ChatRequest / ChatResponse / MessageResponse Pydantic models
web/                 → 纯静态前端（localStorage 管理对话，fetch SSE 流）
```

## 关键约定

- **所有路由函数用 `async def`**
- **数据库操作用 SQLAlchemy async**：`select()` + `await db.execute()`，通过 `Depends(get_db)` 注入 session
- **统一响应格式**：所有 API 返回 `APIResponse(success=..., data=..., error=...)`
- **LLM 客户端**：通过 `Depends(get_llm_client)` 注入 `httpx.AsyncClient`，base_url 指向 Ollama
- **路由前缀**：`/api/v1/`
- **数据库**：SQLite (`agent.db`)，表在 lifespan startup 时自动 `create_all`

## 聊天端点一览

| 路由 | 用途 | 实现方式 | 是否落库 | 输出 |
|------|------|----------|----------|------|
| `POST /api/v1/conversations/` | 完整对话：查历史 → 拼 context → 调 LLM → 存双方消息 | httpx | 是 | JSON |
| `POST /api/v1/chat/stream` | 轻量流式：单条消息透传 Ollama，流式返回 | sse-starlette `EventSourceResponse` | 否 | SSE |
| `POST /api/v1/chat/stream-legacy` | 同上，手动构造 SSE 格式 | `StreamingResponse` | 否 | SSE |

前端目前对接的是 `/chat/stream`。`stream-legacy` 仅保留供学习对比两种 SSE 实现方式的差异。

## 已知问题

- `conversations.py` 的 `list_conversations()` 返回体中 `list` 是 Python 关键字被误用作 dict key，且 `PaginatedResponse` 未正确展开为 dict
- `chat/stream` 推送给前端的 data 中 `'text': 'text'` 是硬编码占位值
- 前端 SSE 解析中 `data.text === 'text'` 检查了这个硬编码值
- `uploads.py` 硬编码了 Linux 路径 `/path/to/save/`，在 Windows 上会报错
- 无测试、无 pyproject.toml、无 requirements.txt
