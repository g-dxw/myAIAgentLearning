# AI Agent 学习打卡

> 开始日期：2026/05/12
> 目标：能独立造一个真正有用的 Agent 产品，不是 Demo，是能跑起来的东西
> 学习方式：主线（Python/FastAPI/Agent 技术）+ 副线（Claude Code 实战），两条线并行

---

## 总进度

| 阶段 | 周次 | 主线：Agent 技术栈 | 副线：CLI Agent 工具 | 状态 |
|------|------|-------------------|---------------------|------|
| 一 | Week 01 | Python 速成 + FastAPI | Claude Code 入门：CLAUDE.md、结对编程 | ✅ |
| 一 | Week 02 | LLM 原理 | 用 Claude Code 调试 API、对比模型输出 | ✅ |
| 一 | Week 03 | Agent 核心循环：Function Calling + Tool Use（手写 Agent Loop） | 对比 Claude Code 的 tool call 设计 | ✅ |
| 二 | Week 04 | RAG 原理与实践 | Claude Code 自定义 Slash Commands + Hooks | 🟡 |
| 二 | Week 05 | 向量数据库 | 用 Claude Code 管理个人知识库（CLAUDE.md 进阶） | ⬜ |
| 二 | Week 06 | LangChain + LangGraph | Claude Code 辅助调试 Agent 状态机 | ⬜ |
| 三 | Week 07 | 多 Agent 协作 | 工具对比：Claude Code vs Cursor vs Aider | ⬜ |
| 三 | Week 08 | **MCP + Skills + 协议生态** | 开发 MCP Server + 写一个 SKILL.md 并接入 Claude Code | ⬜ |
| 三 | Week 09 | **Agent 评测 + 可观测性 + 安全** | 用 Langfuse trace 调试 + 安全审计 | ⬜ |
| 四 | Week 10 | 养老护工项目实战（含 Reflection + Agentic RAG） | Claude Code 全程结对编程 | ⬜ |
| 四 | Week 11 | **部署 + 浏览器 Agent + 沙箱** | browser-use 实战 + E2B 沙箱 | ⬜ |
| 四 | Week 12 | **面试准备 + 记忆管理深度 + 总复盘** | 模拟面试 + 12 周总复盘 | ⬜ |

⬜ 未开始　🟡 进行中　✅ 已完成

> **📍 当前：Week 07（阶段三收官）** — 阶段一-二（Week 01-05）已收官，Week 06-07 LangChain/LangGraph/多Agent 协作已学完。
>
> **⚠️ 大纲更新说明（2026-07）：** Week 08-12 已根据 Agent-Learning-Hub 8 Stage 路线 + 2026 Agent 面试高频考点重新调整。主要变化：
> - Week 08 从"MCP协议"扩展为"MCP + Skills + 协议生态"（补 Skills 概念、A2A/ACP）
> - Week 09 从"评估与优化"扩展为"评测 + 可观测性 + 安全"（补 Langfuse trace、Prompt Injection 防御、沙箱）
> - Week 10 新增 Reflection/Self-Correction 模式 + Agentic RAG 深度（冲突处理/权限隔离/Reranking）
> - Week 11 新增浏览器 Agent（browser-use）+ 沙箱执行（E2B/Modal）
> - Week 12 修正 CrewAI → LangGraph，新增记忆管理深度 + Workflow vs Autonomous 对比

### 副线设计思路

```
副线的目标不是"学会用 Claude Code"，而是"离不开 Claude Code"。

Week 01-03：会用     → 基础交互、CLAUDE.md、理解它的 tool call
Week 04-06：用好     → 自定义工作流、知识索引、辅助调试复杂系统
Week 07-09：会选     → 知道什么时候用 Claude Code、什么时候换 Cursor/Aider
Week 10-12：内化     → 形成你自己的 Agent 辅助开发范式，效率翻倍
```

主线让你**能造 Agent**，副线让你**能驾驭 Agent 工具**。两条线都通了，你才是一个完整的 Agent 开发者。

---

## Week 01 详细进度

| 天 | 主题 | 主线内容 | 副线（Claude Code） | 状态 |
|----|------|---------|---------------------|------|
| Day 01 | 类型语法 + 推导式 + with + async | TS/JS 对照 Python、dataclass、推导式、上下文管理器 | — | ✅ |
| Day 02 | Pydantic v2 数据校验 | BaseModel、Field、field_validator、model_validator、model_json_schema | — | ✅ |
| Day 03 | FastAPI 路由 + 请求参数校验 | Path/Query/Body、APIRouter、response_model、HTTPException | — | ✅ |
| Day 04 | 依赖注入 + 错误处理 | Depends、全局异常处理、中间件、CORS | — | ✅ |
| Day 05 | async/await + 异步数据库 | 事件循环、协程 vs 线程、SQLAlchemy async、Depends(get_db) | 用 Claude Code 审查异步代码 | ✅ |
| Day 06 | API 设计 + 流式响应 + 文件上传 | RESTful 规范、SSE StreamingResponse、UploadFile | 给项目写 CLAUDE.md | ✅ |
| Day 07 | 综合实战：Agent 对话管理平台 | 完整 FastAPI 后端（CRUD + 异步 DB + SSE + 文件上传） | 全程 Claude Code 结对编程 | ✅ |

---

## Week 02 详细进度

| 天 | 主题 | 主线内容 | 副线（Claude Code） | 状态 |
|----|------|---------|---------------------|------|
| Day 01 | Token 机制 + Context Window | Token 是什么、Tokenizer 验证、上下文窗口限制 | 观察 Claude Code 的 token 管理 | ✅ |
| Day 02 | Token 计量 + API 计费 | tiktoken、token 计数实战、各模型价格对比 | 用 Claude Code 分析 API 调用日志 | ✅ |
| Day 03 | Thinking / Effort 机制 | extended thinking、reasoning_effort 参数、思维链 | 对比 Claude Code 的 thinking 输出 | ✅ |
| Day 04 | Streaming 原理 | SSE 协议细节、逐 token 解析、流式 vs 非流式 | Claude Code 的流式输出观察 | ✅ |
| Day 05 | Prompt Caching | cache_control 标记、缓存命中率、成本优化 | 分析 Claude Code 的缓存策略 | ✅ |
| Day 06 | Caching 实战 + 错误重试 | 缓存命中率测试、retry 机制、指数退避 | 给对话 API 加错误重试 | ✅ |
| Day 07 | 产出：对话 API 封装 | 完整 API 客户端（流式+缓存+重试+Token 统计） | 全程 Claude Code 结对编程 | ✅ |

---

## Week 03 详细进度

| 天 | 主题 | 主线内容 | 副线（Claude Code） | 状态 |
|----|------|---------|---------------------|------|
| Day 01 | API 实战调用 | LLM API 四角色、httpx 调 API、流式解析、Token 提取 | 对比 Claude Code 的 API 格式 | ✅ |
| Day 02 | Function Calling 完整流程 | Tool Schema、tool_calls 解析、Handler 分发、结果回传 | 观察 Claude Code 的 tool call 日志 | ✅ |
| Day 03 | Agent Loop 框架 | while True 循环、ToolAgent 类、max_turns 控制 | Claude Code 的 Agent Loop 深度分析 | ✅ |
| Day 04 | 结构化输出 | JSON Mode、Pydantic 反序列化、四种方式对比 | Claude Code 的 Structured Output 使用 | ✅ |
| Day 05 | Tool 设计原则 | 六原则、搜索工具实战、粒度决策、安全性 | Claude Code 工具设计风格分析 | ✅ |
| Day 06-07 | 产出：完整 Agent | 5+ 工具、验证脚本、Agent 总结 | 全程 Claude Code 结对编程 | ✅ |

---

## 学习方式

### 主线 + 副线

```
主线：Python → FastAPI → LLM API → RAG → Agent 框架 → MCP → 部署
副线：Claude Code 实战贯穿始终（写好 CLAUDE.md、学会和 AI 结对编程）
```

主线让你能**造 Agent**，副线让你能**驾驭 Agent 工具**。两条线都通了，你才是一个完整的 Agent 开发者。

### 每日打卡规则

每天学习结束后在对应 `dayXX.md` 的末尾填写：

1. **今日学了什么**（具体知识点，不是"学了 Python"）
2. **写了什么代码**（附文件路径或关键代码片段）
3. **踩了什么坑**（报错信息 + 怎么解决的）
4. **副线笔记**（今天用 Claude Code 做了什么、它说的对/错的地方、下次怎么问更好）
5. **明天计划**

### 核心原则

- **自己决定做什么、为什么**——架构选型、功能需求你定
- **Claude Code 加速怎么做**——重复性代码让它出第一版，你审查修改
- **不做 Demo、做底座**——每个项目都应该是能持续生长的，不是写完就扔的

---

## 产出物清单

每阶段结束时应有的产出：

- [x] Week 01：Agent 对话管理平台（多 Agent + 流式对话 + 异步 DB + 文件上传）
- [x] Week 02：一个对话 API 封装（流式输出 + 缓存 + 错误重试）
- [x] Week 03：一个带工具调用的 Agent（查天气/算数/搜索）
- [ ] Week 04：一个文档问答系统（上传 PDF → 问答）
- [ ] Week 05：一个路线知识库（语义搜索）
- [ ] Week 06：一个多步推理 Agent（路线推荐 → 天气 → 装备清单）
- [ ] Week 07：一个多 Agent 活动策划系统
- [ ] Week 08：一个自定义 MCP Server
- [ ] Week 09：Agent 测试用例 + 评估脚本
- [ ] Week 10-11：养老护工智能记录系统（完整项目）
- [ ] Week 12：综合实战 + 持续迭代

---

## 目录结构

```
AI-Agent-打卡/
├── README.md              ← 你在这里
├── week01/                ✅ 已完成 — FastAPI + Pydantic + 异步 DB
│   ├── day01.md ~ day07.md
│   └── day01/ ~ day07/    每日练习代码
├── week02/                ✅ 已完成 — LLM 原理 + API 客户端封装
│   └── day01.md ~ day07.md
├── week03/                ✅ 已完成 — Agent 核心循环 + Function Calling
│   ├── day01.md ~ day06-07.md
│   └── day01/ ~ day07/    每日练习代码
├── week04/                🟡 进行中 — RAG 原理与实践
│   ├── day01-07.md        本周总览
│   └── day01.md ~ day07.md
├── week05/ ~ week12/      ⬜ 待生成
├── .obsidian/             Obsidian 配置（显示思维导图）
└── .git/                  版本控制
```
