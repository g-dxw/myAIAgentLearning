# Day 05 — async/await + 异步数据库

## 学习目标

深入理解 Python 的 async/await 协程模型，掌握事件循环原理，能区分协程和多线程的适用场景，并能用 SQLAlchemy async 在 FastAPI 中做异步数据库操作。

---

## 一、协程是什么 —— 一张图说清楚

```
同步（阻塞）：
  请求1 ████████████████░░░░（等 DB）
  请求2                            ████████████████░░░░（等 DB）
  请求3                                                    ████████████████░░░░
  → 三个请求串行，总时间 = 3 × (计算 + 等待)

协程（异步非阻塞）：
  请求1 ████░░░░░░░░░░░░░░░░░░░░░░░░░░（等 DB 时主动让出）
  请求2      ████░░░░░░░░░░░░░░░░░░░░░░░░░░（等 DB 时主动让出）
  请求3           ████░░░░░░░░░░░░░░░░░░░░░░░░░░（等 DB 时主动让出）
  → 三个请求"交织"执行，总时间 ≈ 1 × (计算 + 最长等待)
```

**核心理解：** async/await 不是并行，是**协作式多任务**——一个任务主动说"我要等了，你先请"，让出 CPU 给下一个任务。

---

## 二、看懂事件循环（Event Loop）

### 2.1 事件循环就是任务调度器

```python
import asyncio

async def task_a():
    print("A: 开始")
    await asyncio.sleep(1)  # sleep = 模拟 IO 等待
    print("A: 结束")
    return "A 的结果"

async def task_b():
    print("B: 开始")
    await asyncio.sleep(0.5)
    print("B: 结束")
    return "B 的结果"

async def main():
    # 同时启动两个任务，谁先完成先拿结果
    results = await asyncio.gather(task_a(), task_b())
    print(results)

asyncio.run(main())
```

**输出：**
```
A: 开始      ← task_a 启动，遇到 await → 挂起，让给 task_b
B: 开始      ← task_b 启动，遇到 await → 挂起
B: 结束      ← 0.5s 后 task_b 先醒
A: 结束      ← 1.0s 后 task_a 醒了
['A 的结果', 'B 的结果']
```

**事件循环干的事：**
```
┌─────────────────────────────────────────┐
│              事件循环                    │
│                                         │
│  待执行队列: [task_a, task_b]            │
│  等待队列:   [(task_a, sleep 1s), ...]  │
│                                         │
│  每轮循环:                              │
│  1. 检查等待队列：谁的时间到了？移到待执行 │
│  2. 从待执行队列取一个，执行到下一个 await │
│  3. 把这个任务放回等待队列                │
│  4. 重复...                             │
└─────────────────────────────────────────┘
```

### 2.2 await 到底是什么

```python
async def fetch_data():
    # await = "我要等这个操作完成，期间可以让别人用 CPU"
    data = await db.query("SELECT ...")  # DB 去查了，我挂起
    return data

# 等价的心智模型（伪代码）：
# await 后面的东西必须是一个 "可等待对象" (Awaitable)
# 遇到 await → 交出控制权给事件循环 → 事件循环去跑别的任务
# → 等这个 Awaitable 完成了 → 事件循环把我叫回来继续
```

**什么东西可以 await：**
- 另一个 `async def` 函数（协程）
- `asyncio.Task`（被事件循环托管的协程）
- 任何实现了 `__await__` 的对象（如 `asyncio.sleep`）

---

## 三、协程 vs 多线程 —— 什么时候用什么

### 3.1 对比代码

```python
# === 多线程版本（适合 CPU 密集型） ===
import threading
import time

def download(url: str) -> str:
    time.sleep(1)  # 模拟网络 IO
    return f"Content from {url}"

def download_with_threads(urls: list[str]):
    threads = []
    results = []

    def worker(url):
        result = download(url)
        results.append(result)

    for url in urls:
        t = threading.Thread(target=worker, args=(url,))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()  # 等所有线程完成

    return results

# === 协程版本（适合 IO 密集型） ===
import asyncio

async def async_download(url: str) -> str:
    await asyncio.sleep(1)  # 模拟网络 IO
    return f"Content from {url}"

async def download_with_coroutines(urls: list[str]):
    tasks = [async_download(url) for url in urls]
    results = await asyncio.gather(*tasks)
    return results
```

### 3.2 决策表

| 场景 | 用协程？ | 用线程？ | 原因 |
|------|---------|---------|------|
| 网络请求（等 HTTP 响应） | ✅ | 也可以 | 协程更轻量，没有 GIL 开销 |
| 数据库查询（等 DB 返回） | ✅ | 也可以 | 同上，Python 的 async DB 驱动很成熟 |
| LLM API 调用（等远端生成） | ✅ | 也可以 | Agent 场景核心，`httpx.AsyncClient` 直接支持 |
| 图片/视频处理 | ❌ | ✅ | CPU 密集型，协程没法并行计算 |
| 大文件读写 | ✅ | ✅ | 现代 OS 有 AIO，但普通文件 IO 线程也行 |
| 大量并发连接（WebSocket） | ✅ | ❌ | 线程内存开销 8MB/个，协程 ~KB 级 |

**一个经验法则：**
```python
# IO 等待 → await（协程）
# CPU 计算 → run_in_executor（丢给线程池）
import asyncio

async def process():
    # 网络请求 —— await 协程
    data = await fetch_from_api()

    # CPU 密集计算 —— 丢给线程池，不阻塞事件循环
    result = await asyncio.to_thread(heavy_computation, data)  # Python 3.9+

    return result
```

### 3.3 协程的坑

```python
# ❌ 坑 1：在协程里调用同步阻塞函数 → 整个事件循环卡死
async def bad():
    time.sleep(5)  # ← 不要！这会让事件循环冻结 5 秒
    return "done"

# ✅ 正确：用 asyncio.sleep
async def good():
    await asyncio.sleep(5)  # 挂起 5 秒，事件循环可以干别的
    return "done"

# ❌ 坑 2：忘记 await → 协程不会执行
async def main():
    fetch_data()  # ← 没有 await！返回一个协程对象，但不会执行
    # RuntimeWarning: coroutine 'fetch_data' was never awaited

# ✅ 正确：
async def main():
    await fetch_data()  # 执行协程并等待结果
```

---

## 四、异步数据库操作

### 4.1 为什么 Agent 项目需要异步数据库

```python
# 同步：每次等 DB 返回才处理下一个请求
@app.post("/chat")
def chat(request: ChatRequest):
    history = db.query(Message).filter(...).all()  # 阻塞 50ms
    result = client.messages.create(...)            # 阻塞 2000ms
    db.add(result)                                  # 阻塞 20ms
    return result
# → 10 个并发请求 = 10 个线程，内存爆炸

# 异步：等待时处理其他请求
@app.post("/chat")
async def chat(request: ChatRequest):
    history = await db.execute(select(Message).filter(...))  # 让出 50ms
    result = await async_client.messages.create(...)         # 让出 2000ms
    await db.commit()                                        # 让出 20ms
    return result
# → 10 个并发请求 = 1 个事件循环，内存几乎不变
```

### 4.2 SQLAlchemy async 配置

```python
# pip install sqlalchemy[asyncio] asyncpg  (PostgreSQL)
# 或 pip install sqlalchemy[asyncio] aiomysql  (MySQL)

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Integer, Text, DateTime, select
from datetime import datetime

# 1. 异步引擎
DATABASE_URL = "postgresql+asyncpg://user:pass@localhost:5432/agent_db"
engine = create_async_engine(DATABASE_URL, echo=False)  # echo=True 看 SQL 日志

# 2. 异步会话工厂
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# 3. 模型基类
class Base(DeclarativeBase):
    pass

# 4. 定义模型
class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String(36), index=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)
```

### 4.3 依赖注入异步会话

```python
from fastapi import FastAPI, Depends
from sqlalchemy.ext.asyncio import AsyncSession

app = FastAPI()

async def get_db() -> AsyncSession:
    """每个请求一个独立的异步数据库会话"""
    async with AsyncSessionLocal() as session:
        yield session
        # 请求结束后自动关闭（或回滚）

@app.post("/conversations/{conv_id}/messages")
async def add_message(
    conv_id: str,
    role: str,
    content: str,
    db: AsyncSession = Depends(get_db),
):
    msg = Message(conversation_id=conv_id, role=role, content=content)
    db.add(msg)
    await db.commit()
    await db.refresh(msg)
    return {"id": msg.id, "created_at": msg.created_at}


@app.get("/conversations/{conv_id}/messages")
async def get_messages(
    conv_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv_id)
        .order_by(Message.created_at)
        .limit(50)
    )
    messages = result.scalars().all()
    return [
        {"role": m.role, "content": m.content, "created_at": m.created_at.isoformat()}
        for m in messages
    ]
```

**异步 SQLAlchemy 关键注意点：**
- `session.execute(select(...))` 返回 `Result`，需要 `await`
- `session.commit()` 需要 `await`
- `result.scalars().all()` 同步即可（数据已取回内存）
- 绝对不要在异步 session 里用同步 session 的方法

### 4.4 Agent 场景常用查询

```python
# 查最近 N 条消息作为上下文
async def get_context_messages(db: AsyncSession, conv_id: str, limit: int = 20):
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    messages = result.scalars().all()
    return list(reversed(messages))  # 正序返回

# 统计 token 用量
from sqlalchemy import func

async def get_token_stats(db: AsyncSession, user_id: str, days: int = 7):
    since = datetime.now() - timedelta(days=days)
    result = await db.execute(
        select(
            func.count(Message.id).label("total_messages"),
            func.avg(func.length(Message.content)).label("avg_content_length"),
        )
        .where(Message.created_at >= since)
    )
    return result.one()._asdict()
```

---

## 五、完整实战 —— 异步 Agent API

把前面 4 天学的内容串联，写一个完整的异步 Agent 对话 API：

```python
"""
异步 Agent 对话 API
- SqlAlchemy async 存储对话历史
- httpx async 调用 LLM
- Depends 注入数据库和 LLM 客户端
- 全局异常处理和日志
"""

from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import (
    create_async_engine, AsyncSession, async_sessionmaker
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Text, DateTime, select, func
from pydantic import BaseModel, Field
from typing import Literal
import httpx
import os
import time
from datetime import datetime

# ==========================================
# 初始化
# ==========================================
app = FastAPI(title="Async Agent API", version="0.3.0")

engine = create_async_engine(
    "postgresql+asyncpg://user:pass@localhost:5432/agent_db", echo=False
)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# ==========================================
# 数据模型（Pydantic）
# ==========================================
class ChatRequest(BaseModel):
    conversation_id: str = Field(min_length=1)
    message: str = Field(min_length=1, max_length=4000)
    model: str = Field(default="claude-sonnet-4-6")

class ChatResponse(BaseModel):
    reply: str
    model: str
    conversation_id: str
    usage: dict


# ==========================================
# 数据库模型（SQLAlchemy）
# ==========================================
class Base(DeclarativeBase):
    pass

class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(String(36), index=True)
    role: Mapped[str] = mapped_column(String(20))  # user / assistant
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)


# ==========================================
# 依赖注入
# ==========================================
async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

async def get_llm_client():
    async with httpx.AsyncClient(
        base_url="https://api.anthropic.com/v1",
        headers={
            "x-api-key": os.getenv("ANTHROPIC_API_KEY", ""),
            "anthropic-version": "2023-06-01",
        },
        timeout=60,
    ) as client:
        yield client


# ==========================================
# 中间件 & 异常处理
# ==========================================
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    elapsed = (time.time() - start) * 1000
    print(f"[{time.strftime('%H:%M:%S')}] {request.method} {request.url.path} → {response.status_code} ({elapsed:.0f}ms)")
    return response

@app.exception_handler(Exception)
async def global_handler(request: Request, exc: Exception):
    print(f"[ERROR] {exc}")
    return JSONResponse(status_code=500, content={"error": True, "detail": str(exc)})


# ==========================================
# 核心：异步 Agent 对话路由
# ==========================================
@app.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    llm: httpx.AsyncClient = Depends(get_llm_client),
):
    # 1. 异步查历史消息 → 同时事件循环可以处理其他请求
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == request.conversation_id)
        .order_by(Message.created_at)
        .limit(20)
    )
    history = result.scalars().all()

    # 2. 构建 LLM 请求
    messages = [
        {"role": m.role, "content": m.content}
        for m in history
    ]
    messages.append({"role": "user", "content": request.message})

    # 3. 异步调 LLM → 等待期间事件循环继续处理其他请求
    resp = await llm.post("/messages", json={
        "model": request.model,
        "max_tokens": 4096,
        "messages": messages,
    })
    data = resp.json()
    reply_text = data["content"][0]["text"]

    # 4. 异步存用户消息
    user_msg = Message(
        conversation_id=request.conversation_id,
        role="user",
        content=request.message,
    )
    db.add(user_msg)

    # 5. 异步存 Assistant 回复
    assistant_msg = Message(
        conversation_id=request.conversation_id,
        role="assistant",
        content=reply_text,
    )
    db.add(assistant_msg)

    # 6. 异步提交
    await db.commit()

    return ChatResponse(
        reply=reply_text,
        model=request.model,
        conversation_id=request.conversation_id,
        usage=data["usage"],
    )


@app.get("/health")
async def health():
    return {"status": "ok"}


# 启动: uvicorn main:app --reload
```

**这段代码的异步链路：**
```
收到 POST /chat
  → await db.execute(...)      ← 挂起，事件循环去处理下一个请求
  → await llm.post(...)         ← 挂起，事件循环去处理下一个请求
  → await db.commit()          ← 挂起，事件循环去处理下一个请求
  → return ChatResponse
```

---

## 六、今日练习（约 2.5 小时）

### 练习 1：理解事件循环（20 min）

```python
import asyncio

# 写 3 个协程，每个打印 "开始 → 等待 X 秒 → 结束"
# 用 asyncio.gather 同时跑，观察输出顺序
# 验证：等待时间短的先结束

async def worker(name: str, delay: float):
    print(f"{name} 开始 (等待 {delay}s)")
    await asyncio.sleep(delay)
    print(f"{name} 结束")
    return f"{name} 结果"

async def main():
    results = await asyncio.gather(
        worker("A", 2.0),
        worker("B", 0.5),
        worker("C", 1.0),
    )
    print(f"全部完成: {results}")

asyncio.run(main())
```

### 练习 2：协程 vs 线程性能对比（25 min）

```python
import asyncio
import threading
import time

# 模拟 IO 密集任务（如调 LLM API）
async def io_task_async(task_id: int) -> str:
    await asyncio.sleep(0.1)  # 模拟 100ms IO
    return f"Task-{task_id}"

def io_task_sync(task_id: int) -> str:
    time.sleep(0.1)
    return f"Task-{task_id}"

# 对比 500 个任务：
# 协程版：~0.1s（全都"同时"等）
# 线程版：需要 500 个线程，创建销毁耗时 + 内存 500×8MB ≈ 4GB
# 同步版：~50s（500 × 0.1s 串行）

async def benchmark_async():
    start = time.time()
    tasks = [io_task_async(i) for i in range(500)]
    await asyncio.gather(*tasks)
    print(f"协程 500 任务: {time.time() - start:.2f}s")

def benchmark_threads():
    start = time.time()
    threads = [threading.Thread(target=io_task_sync, args=(i,)) for i in range(500)]
    for t in threads: t.start()
    for t in threads: t.join()
    print(f"线程 500 任务: {time.time() - start:.2f}s")
```

### 练习 3：异步数据库 CRUD（40 min）

用 SQLite（无需额外安装数据库）做练习：

```python
# pip install aiosqlite
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import select

engine = create_async_engine("sqlite+aiosqlite:///test.db", echo=True)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

class Agent(Base):
    __tablename__ = "agents"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    model: Mapped[str]

# 实现 async 函数：
# 1. create_tables() → 初始化建表
# 2. create_agent(name, model) → 插入
# 3. list_agents() → 查询所有
# 4. update_agent_model(id, new_model) → 更新
# 5. delete_agent(id) → 删除
```

### 练习 4：Agent 对话 API 加上数据库（60 min）

把 Day 03/04 的 Agent 配置 API 升级为异步数据库版：
- 用 SQLAlchemy async 替代内存 `list`
- 每个请求通过 `Depends(get_db)` 获取异步 session
- 添加一个 `GET /stats` 端点，用 `func.count` 统计 agent 数量

---

## 七、踩坑记录

```
// 写代码时记录你遇到的所有坑：

[ ] 坑 1：____________________
解决：____________________

[ ] 坑 2：____________________
解决：____________________
```

**常见坑预警：**

| 坑 | 表现 | 解决 |
|----|------|------|
| ❌ `func()` 里混用 `await` 和同步调用 | `RuntimeWarning: coroutine was never awaited` | 所有 `async def` 函数必须 `await` |
| ❌ `asyncio.run()` 在已有事件循环的环境里调用 | `RuntimeError: asyncio.run() cannot be called from a running event loop` | FastAPI 里不需要 `asyncio.run()`，直接用 `await` |
| ❌ 异步 session 忘记 `await commit()` | 数据没写入数据库，也不报错 | 每次 `db.add` 后记得 `await db.commit()` |
| ❌ `session.get()` 返回 None | `session.get(Model, id)` 是同步的，但 `await session.execute(select(...))` 是异步的 | 查询统一用 `await db.execute(select(...))` |
| ❌ 在协程里调 `time.sleep()` | 整个事件循环冻结 | 用 `await asyncio.sleep()` |

---

## Day 05 检查清单

- [ ] 能解释协程和线程的区别（并发 vs 并行）
- [ ] 理解 `await` 的本质是"交出控制权"
- [ ] 能用 `asyncio.gather` 并发跑多个协程
- [ ] 知道什么时候用协程、什么时候用线程
- [ ] 能配置 SQLAlchemy async engine + AsyncSession
- [ ] 能用 `Depends(get_db)` 注入异步数据库会话
- [ ] 能写 `await db.execute(select(...))` 异步查询
- [ ] 能在单个路由里串联：查 DB → 调 LLM → 存 DB（全程 async）
- [ ] 知道 `asyncio.run()` 只在脚本入口调用，FastAPI 内部不需要

---

## 副线：Claude Code 实战（15 min）

> 主线学 Python，副线学怎么用好你手上的 Claude Code。两条线并行，到最后你能自己造 Agent，也能驾驭现成的 Agent 工具。

### 今天的任务：让 Claude Code 审查你的异步代码

把你在练习 3 或练习 4 中写的代码文件拖到 Claude Code 对话里，逐一执行：

```
# 1. 让它检查 async/await 是否正确
"帮我检查这个文件里的异步代码有没有问题——有没有忘记 await 的？
有没有在协程里调了同步阻塞函数？有没有 asyncio.run 放错地方的？"

# 2. 让它重构一个函数
"这个 chat 函数太长了，帮我拆成几个小函数，每个职责单一"

# 3. 让它解释你不懂的地方
"这段 SQLAlchemy async 代码里，为什么 commit 需要 await，但 scalars().all() 不需要？"
```

**检验标准：** Claude Code 给出了你没注意到的问题，或者帮你发现了一个 bug。如果它只是说"看起来没问题"，说明你的提示词不够具体——把代码范围缩小到单个函数再问。

### CLI Agent 认知笔记

```
// 记录今天用 Claude Code 的感受：

今天让它帮做了什么：____________________
它说的有道理的地方：____________________
它说错了 / 没帮上忙的地方：____________________
下次怎么问更好：____________________
```

---

## 明天计划

- [ ] Day 06 — API 设计 + 流式响应 + 文件上传；副线：给项目写 CLAUDE.md
