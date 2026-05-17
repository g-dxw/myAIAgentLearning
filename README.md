# AI Agent 学习打卡

> 开始日期：2026/05/12
> 目标：能独立造一个真正有用的 Agent 产品，不是 Demo，是能跑起来的东西
> 学习方式：主线（Python/FastAPI/Agent 技术）+ 副线（Claude Code 实战），两条线并行

---

## 总进度

| 阶段 | 周次 | 主线：Agent 技术栈 | 副线：CLI Agent 工具 | 状态 |
|------|------|-------------------|---------------------|------|
| 一 | Week 01 | Python 速成 + FastAPI | Claude Code 入门：CLAUDE.md、结对编程 | 🟡 |
| 一 | Week 02 | LLM 原理 | 用 Claude Code 调试 API、对比模型输出 | ⬜ |
| 一 | Week 03 | Tool Use + 结构化输出 | 拆解 Claude Code 的 tool call 循环 | ⬜ |
| 二 | Week 04 | RAG 原理与实践 | Claude Code 自定义 Slash Commands + Hooks | ⬜ |
| 二 | Week 05 | 向量数据库 | 用 Claude Code 管理个人知识库（CLAUDE.md 进阶） | ⬜ |
| 二 | Week 06 | LangChain + LangGraph | Claude Code 辅助调试 Agent 状态机 | ⬜ |
| 三 | Week 07 | 多 Agent 协作 | 工具对比：Claude Code vs Cursor vs Aider | ⬜ |
| 三 | Week 08 | MCP 协议 | 开发 MCP Server 并接入 Claude Code 验证 | ⬜ |
| 三 | Week 09 | Agent 评估与优化 | 用 Claude Code 写评测脚本 + 回归测试 | ⬜ |
| 四 | Week 10 | 养老护工项目实战 | Claude Code 全程结对编程驱动开发 | ⬜ |
| 四 | Week 11 | 部署上线 | Claude Code 集成 CI/CD 自动化工作流 | ⬜ |
| 四 | Week 12 | 综合实战 + 持续迭代 | Claude Code 工作流定型：你的专属开发范式 | ⬜ |

⬜ 未开始　🟡 进行中　✅ 已完成

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
| Day 04 | 依赖注入 + 错误处理 | Depends、全局异常处理、中间件、CORS | — | 🟡 |
| Day 05 | async/await + 异步数据库 | 事件循环、协程 vs 线程、SQLAlchemy async、Depends(get_db) | 用 Claude Code 审查异步代码 | ⬜ |
| Day 06 | API 设计 + 流式响应 + 文件上传 | RESTful 规范、SSE StreamingResponse、UploadFile | 给项目写 CLAUDE.md | ⬜ |
| Day 07 | 综合实战：Agent 对话管理平台 | 完整 FastAPI 后端（CRUD + 异步 DB + SSE + 文件上传） | 全程 Claude Code 结对编程 | ⬜ |

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

- [ ] Week 01：Agent 对话管理平台（多 Agent + 流式对话 + 异步 DB + 文件上传）
- [ ] Week 02：一个对话 API 封装（流式输出 + 缓存 + 错误重试）
- [ ] Week 03：一个带工具调用的 Agent（查天气/算数/搜索）
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
├── week01/                ✅ 已拆分为每日文件
│   ├── day01.md           ✅ Python 类型语法对照
│   ├── day02.md           ✅ Pydantic v2
│   ├── day03.md           ✅ FastAPI 路由
│   ├── day04.md           ✅ Depends + 异常处理
│   ├── day05.md           ✅ async/await + 异步 DB + 副线
│   ├── day06.md           ✅ SSE + 文件上传 + 副线
│   ├── day07.md           ✅ 综合实战 + 全程 Claude Code
│   └── day01/             Day 01 练习代码
├── week02/ ~ week12/      ⬜ 待拆分
├── .obsidian/             Obsidian 配置（显示思维导图）
└── AI-Agent-学习计划.md   原始 12 周学习计划（参考）
```
