# Day 03 — Skills 概念：Skill vs Tool vs MCP vs Prompt

## 学习目标

Day 01-02 我们花了两天啃 MCP：Day 01 搞清楚 MCP 是把 `@tool` 从"同进程函数"升级成"跨进程标准协议"，Day 02 手写了一个暴露 Tool / Resource / Prompt 的 MCP Server，还接入了 Claude Code 验证。你现在明白 MCP 解决的是"Agent 怎么连接外部世界"的问题——标准化、跨语言、可发现。

但今天要聊的东西更微妙：**Skills**。Day 01-02 的 MCP 是"接口层"的事，Skills 是"知识层"的事。很多初学者一上来就把 Skill 理解成"一段提示词"，这大错特错。Skill 不是提示词，是一整个**能力包**。而且你会发现，Week 07 我们也学过一个叫"Skills"的东西——那是 LangChain 的 `load_skill` 模式，和今天要讲的 Claude Code Skills 完全是两码事。名字一样，概念不同，这是 2026 年面试最爱挖的坑。

学完今天你能：

1. 理解 Claude Code Skills 的本质：可发现、可版本化、可分发的"能力包"，不是提示词
2. 能区分 Skill / Tool / MCP / Prompt 四个概念的精确差异
3. 理解 Skills 的"按需加载"机制：启动时只加载名字和描述，调用时才加载完整内容
4. 知道 Week 07 的 LangChain Skills 模式和 Claude Code Skills 是完全不同的概念

---

## 一、Skills 是什么：不是提示词，是能力包

### 1.1 最常见的误区：Skill 就是提示词

很多人第一次接触 Skills，脑子里第一反应是："这不就是一段 prompt 吗？把 system_prompt 存成文件，用的时候读出来注入，就叫 Skill 了。"

错。这是把 Skills 降维成了"提示词模板"。

提示词是什么？一段文本指令。它没有结构、没有附件、没有版本、没有文件。你把一段 prompt 存成 `weather_prompt.txt`，读出来塞进 messages，这叫"读文件"，不叫"Skill"。

Skill 的本质是：**把一堆文件（包括提示词、脚本、模板），按约定结构打包成一个能力包**。注意是"一堆文件"——不是一个 txt，是一个文件夹。文件夹里有一个核心定义文件（`SKILL.md`），还可以挂审查清单、辅助脚本、模板文件。这才是 Skill。

打个比方：提示词是"一张纸条"，Skill 是"一个工具箱"——工具箱里有一张操作说明（SKILL.md），还可能有扳手、螺丝刀、零件清单。你不会把工具箱说成"一张纸条"。

### 1.2 Claude Code 中 Skill 的物理形态

在 Claude Code 中，Skill 就是 `.claude/skills/` 目录下的一个文件夹。文件夹名字就是 Skill 的名字，里面必须有一个 `SKILL.md` 作为核心定义文件。

来看一个典型的 Skill 文件结构：

```
.claude/skills/
└── code-review/            ← Skill 的名字叫 code-review
    ├── SKILL.md            ← 核心定义文件（必须有）
    ├── checklist.md        ← 审查清单模板（可选）
    └── analyze.py         ← 辅助脚本（可选）
```

注意三个关键点：

1. **`.claude/skills/` 是约定路径**：Claude Code 启动时会扫描这个目录，自动发现里面的所有 Skill。你不用手动注册，放进去就行。
2. **`SKILL.md` 是必须的**：这是 Skill 的"身份证"。没有它，Claude Code 不认这个文件夹。
3. **其他文件是可选的**：`checklist.md`、`analyze.py` 这些是"附件"，SKILL.md 里可以引用它们，调用 Skill 时会按需加载。

### 1.3 SKILL.md 的结构：frontmatter + 正文

`SKILL.md` 分两部分：开头的 YAML frontmatter（元信息）+ 下面的 Markdown 正文（流程正文）。

```markdown
---
name: code-review
description: 对代码进行全面审查，检查安全、性能、可维护性
---

# 代码审查流程

## 步骤
1. 读取目标代码文件
2. 检查安全问题（SQL注入、XSS、硬编码密钥）
3. 检查性能问题（N+1查询、不必要的循环）
4. 检查可维护性（命名、注释、复杂度）

## 验收标准
- 输出审查报告
- 标注严重程度（高/中/低）
- 给出修复建议
```

拆开看：

- **`name`**：Skill 的唯一标识。斜杠命令 `/code-review` 就是靠它触发的。
- **`description`**：一句话说清这个 Skill 干嘛的。这句话极其关键——Claude 启动时只读这一个字段来"知道有这个能力"，用户说话时 Claude 也是靠这句话判断"要不要自动调用这个 Skill"。描述写得烂，Skill 就永远不被触发。
- **正文**：真正的"流程知识"。这里写的是"怎么完成这类任务"的步骤和验收标准。这部分只有在 Skill 被调用时才进上下文。

> **前端工程师的类比：** 你可以把 SKILL.md 想成 Vue 组件的 `.vue` 文件——`frontmatter` 像组件的 `props` 声明（对外暴露的接口），正文像 `<template>` + `<script>`（真正的内容）。而整个 Skill 文件夹就像一个组件目录，里面可以拆 `.vue`、`.css`、`utils.ts` 等子文件。

### 1.4 Skill 和提示词的本质差别

把两者的差异用一张表说清楚：

| 维度 | 提示词（Prompt） | Skill |
|------|------------------|-------|
| 物理形态 | 一段文本 | 一个文件夹（含 SKILL.md + 附件） |
| 包含内容 | 纯文字指令 | 流程步骤 + 模板 + 脚本 + 验收标准 |
| 复用方式 | 复制粘贴 | 放进 `.claude/skills/` 自动发现 |
| 版本管理 | 难（散落在各处） | 天然支持（整个文件夹 git 管理） |
| 可发现性 | 无（得手动记起来用） | 有（Claude 启动时扫描） |
| 触发方式 | 手动拼进 messages | 斜杠命令 `/skill-name` 或自动匹配 |
| 占用 token | 全程占用 | 按需加载（见第三节） |

一句话：**提示词是 Skill 的"一部分"（正文里的流程描述），但 Skill 不等于提示词**。Skill 是提示词的超集——它把提示词、模板、脚本打包成一个可发现、可版本化、可分发的整体。

---

## 二、Skill vs Tool vs MCP vs Prompt 四概念辨析

### 2.1 2026 年最容易混淆的四个概念

这四个概念是 2026 年面试和实际开发中最容易混淆的。原因有两个：一是它们都"给 Agent 加能力"，看起来都在干同一件事；二是名字有重叠（比如 Week 07 的 LangChain Skills 和 Claude Code Skills 都叫"Skills"）。

但它们的本质、生命周期、加载机制完全不同。搞清楚这四个概念的差异，是理解整个 Agent 生态的基础。

### 2.2 四概念详细对比表

| 维度 | Tool | Prompt | MCP | Skill |
|------|------|--------|-----|-------|
| 本质 | 可调用的函数 | 一次性指令 | 标准化工具协议 | 可复用的能力包 |
| 生命周期 | 单次调用 | 单次使用 | 跨进程持续 | 可发现、可版本化 |
| 内容 | 函数代码 | 文本指令 | Server 进程 | 文件夹（含 SKILL.md + 脚本 + 模板） |
| 加载时机 | Agent 运行时 | 对话开始时 | Client 连接时 | 被调用时才加载完整内容 |
| 占用 token | 描述+返回值 | 全程占用 | 工具描述 | 启动时只占名字描述（几十 token） |
| 例子 | get_weather(city) | "你是天气助手" | MCP Server | code-review 流程 |
| 比喻 | 手 | 嘴 | 神经接口 | 大脑的知识 |

逐行解读：

- **Tool（手）**：一个函数，能被 Agent 调用并返回结果。生命周期是"单次调用"——调完就结束，下次需要再调。Week 06 的 `@tool` 就是这个。
- **Prompt（嘴）**：一段一次性指令，告诉 Agent"你是谁、该干嘛"。它全程占着上下文，从对话开始到结束。
- **MCP（神经接口）**：Day 01-02 学的，标准化协议，让 Agent 跨进程连接外部工具。它启动时建立连接，持续存在。
- **Skill（大脑的知识）**：一整套流程知识，平时不占上下文，用到才加载。它最聪明的地方是"可发现"——Claude 知道有哪些 Skill 可用，但不用就不加载。

### 2.3 面试金句：四个比喻

> **面试金句：** Tool 是"手"（能抓东西），Prompt 是"嘴"（会说话），MCP 是"神经接口"（连接外部），Skill 是"大脑的知识"（知道怎么做一类事）。

这四个比喻要记牢。面试官问"Skill 和 Tool 有什么区别"，你答"Tool 是手，Skill 是大脑的知识"——手是动作接口，知识是流程方法。手能抓一次东西，知识是一整套方法论。一次查询用 Tool，一套审查流程用 Skill。

### 2.4 Week 07 的 LangChain Skills vs Claude Code Skills

这是最大的坑。Week 07 我们学过"Skills 模式"——那是 LangChain 的四大模式之一。今天讲的也是"Skills"——Claude Code 的 Skills。名字一模一样，概念完全不同。

| 维度 | Week 07 LangChain Skills | Claude Code Skills |
|------|--------------------------|-------------------|
| 是什么 | 一个 `load_skill` 工具 | 一个文件夹 |
| 内容 | 加载一段 prompt 文本 | SKILL.md + 脚本 + 模板 |
| 载体 | Python 代码里的字典/函数 | `.claude/skills/` 目录 |
| 加载方式 | Agent 调用工具，返回 prompt 文本 | 斜杠命令或自动匹配，加载整个能力包 |
| 用在哪 | LangChain Agent 框架内 | Claude Code CLI 环境 |

回忆 Week 07 Day 04 的代码：

```python
# Week 07 的 Skills：一个工具，加载一段 prompt
@tool
def load_skill(skill_name: str) -> str:
    """加载指定领域的专业知识。"""
    skills = {
        "route": "路线知识：海拔/难度/里程/季节注意事项...",
        "weather": "气象知识：降水/风力/温差/穿衣建议...",
    }
    return skills.get(skill_name, "未知技能")
```

这里的 `load_skill` 是一个 Python 工具函数，返回的是一段 prompt 文本。它是 Week 07 的"动态知识注入"模式，本质是"单 Agent 按需补脑"。

而 Claude Code Skills 是一个完整的文件夹：

```
# Claude Code 的 Skills：一个能力包文件夹
.claude/skills/code-review/
├── SKILL.md          # 流程定义（不是普通 prompt）
├── checklist.md      # 审查清单模板
└── analyze.py        # 辅助脚本
```

它不只包含 prompt，还包含模板、脚本、验收标准——是一整套"怎么完成代码审查这件事"的方法论。

> **关键认知：** 名字一样，概念不同。Week 07 的 Skills 是 LangChain 框架内的"动态知识加载工具"；Claude Code 的 Skills 是一个可发现、可版本化、可分发的能力包文件夹。面试时一定要说清楚是哪个"Skills"，否则容易被面试官追着问。

### 2.5 四个概念在同一任务里的分工

用一个"代码审查"任务把四个概念串起来，看它们各自扮演什么角色：

```
用户："帮我审查 auth.py 这个文件"
    │
    ▼
┌─────────────────────────────────────────────┐
│ Claude（Agent 大脑）                          │
│                                              │
│ Prompt（嘴）："你是代码审查助手..."  ← 全程在  │
│                                              │
│ Skill（大脑的知识）：code-review              │
│   ↓ 检测到用户要做代码审查                    │
│   ↓ 加载 SKILL.md 正文（审查流程步骤）         │  ← 按需加载
│                                              │
│ Tool（手）：read_file(path)                   │
│   ↓ 调用，读 auth.py 内容                     │  ← 单次调用
│                                              │
│ MCP（神经接口）：连接外部数据库的 MCP Server    │
│   ↓ 调用 search_cve 查已知漏洞                │  ← 跨进程
│                                              │
│ → 综合所有信息，输出审查报告                   │
└─────────────────────────────────────────────┘
```

看明白了吗？同一个任务里，四个概念各司其职：

- **Prompt** 全程在场，定义 Agent 的角色和基本行为
- **Skill** 按需加载，提供"怎么做代码审查"的流程方法论
- **Tool** 单次调用，执行"读文件"这个具体动作
- **MCP** 跨进程连接，调用外部系统的"查漏洞"接口

它们不是互斥的替代关系，而是**协作关系**——一个完整的 Agent 系统会同时用到这四样。

---

## 三、Skills 的按需加载机制

### 3.1 Skills 最聪明的设计：启动时不加载完整内容

Skills 最精妙的设计是**按需加载**（lazy loading）。Claude Code 启动时不会把所有 Skill 的完整内容全读进上下文——那跟 CLAUDE.md 有什么区别？它只读每个 Skill 的名字和描述，这些信息加起来才几十 token。

完整内容（SKILL.md 正文 + 附件脚本）只有在 Skill 被实际调用时才加载进上下文。这意味着你可以在 `.claude/skills/` 下放 20 个 Skill，启动时它们总共只占一两千 token，而真正用到的可能只有一两个。

### 3.2 加载流程图解

```
1. Claude Code 启动
        │
        ▼
2. 扫描 .claude/skills/ 目录
   发现：code-review/、deploy-check/、test-gen/
        │
        ▼
3. 读取每个 SKILL.md 的 frontmatter（只读 name + description）
   code-review    → "对代码进行全面审查..."     （约 30 token）
   deploy-check   → "部署前检查清单..."          （约 25 token）
   test-gen       → "为函数生成测试用例..."      （约 25 token）
   总共 ≈ 80 token  ← 非常省
        │
        ▼
4. 用户说："帮我审查 auth.py"
        │
        ▼
5. Claude 根据描述判断："这是代码审查任务"
   匹配到 code-review 这个 Skill
        │
        ▼
6. 此时才加载 code-review/SKILL.md 的完整正文
   + checklist.md（正文里引用了它）
   （可能几百上千 token，但只有用到时才花）
        │
        ▼
7. Claude 按照加载的流程步骤执行审查
```

关键在第 3 步：启动时只加载 frontmatter 的 `name` + `description`，这两个字段加起来通常只有几十 token。这就是为什么你放再多 Skill，启动开销都很小——因为完整内容是"用到才进上下文"。

### 3.3 和 CLAUDE.md 的对比

CLAUDE.md 是 Claude Code 的"全局配置文件"，放在项目根目录，每次对话都全程加载。它和 Skills 的加载策略正好相反：

| 维度 | CLAUDE.md | Skills |
|------|-----------|--------|
| 加载时机 | 全程加载 | 按需加载 |
| 占 token | 高（全程占着） | 低（启动时只占名字描述） |
| 内容性质 | 事实信息（构建命令、目录结构、规范） | 流程步骤（审查流程、部署清单） |
| 适合放什么 | "这个项目用 pnpm"、"目录结构是 src/..." | "代码审查要查这 5 项"、"部署前过这个清单" |

简单说：

- **CLAUDE.md**：随时需要知道的事实，全程在场。比如"这个项目用 pnpm 不是 npm"——这种信息每轮对话都可能用到，必须常驻。
- **Skills**：只有特定任务才需要的流程，用到才加载。比如"代码审查的 7 个步骤"——只有做审查时才需要，平时放着不占 token。

### 3.4 和 Subagents 的对比

Subagents（Week 07 Day 02 学的）也是"按需"的，但它和 Skills 的"按需"机制完全不同：

| 维度 | Skills | Subagents |
|------|--------|-----------|
| 执行位置 | 主线程（当前对话上下文） | 独立上下文（隔离子进程） |
| 中间过程 | 能看到 | 看不到，只返回结论 |
| 上下文污染 | 会注入主上下文 | 不污染主上下文 |
| 适合 | 流程步骤（审查清单） | 脏活累活（大量搜索、日志分析） |

- **Skills 在主线程执行**：Skill 的内容加载进来后，Claude 在当前上下文里按步骤执行。你能看到中间每一步在干什么，但代价是这些步骤会占用主上下文的 token。
- **Subagents 在独立上下文执行**：子 Agent 在一个隔离的上下文里跑完整 ReAct 循环，跑完只把"结论"回传给主 Agent。中间的搜索结果、推理过程都被关在子上下文里，不污染主上下文。

一句话：**Skills 是"在主线程翻开手册照着做"，Subagents 是"派一个人去后台干完汇报结论"**。

### 3.5 算一笔 token 账：按需加载到底省了多少

光说"按需加载省 token"没概念，我们来算一笔账。假设你有个项目，需要 6 个 Skill，每个 Skill 的 SKILL.md 正文平均 800 token，加上附件脚本平均 400 token，单个 Skill 完整加载约 1200 token。

**方案 A：全部常驻（假设的方式，非实际）**

```
6 个 Skill × 1200 token = 7200 token  ← 全程占着
每次对话都要带这 7200 token，不管用不用
```

**方案 B：Skills 按需加载（实际机制）**

```
启动时：6 个 Skill × (name + description) ≈ 6 × 30 = 180 token
调用 code-review 时：180 + 1200 = 1380 token  ← 只有这一个进上下文
其他 5 个 Skill 仍然只占 150 token
总共 ≈ 1530 token  ← 比方案 A 省了 5670 token
```

| 方案 | 启动时 | 调用 1 个 Skill 后 | 一次对话总占用 |
|------|--------|-------------------|---------------|
| 全部常驻 | 7200 token | 7200 token | 7200 token |
| 按需加载 | 180 token | 1530 token | 1530 token |

省了将近 80%。这就是按需加载的价值——你可以在项目里放很多 Skill 而不用担心启动变慢或上下文被撑爆。**用到才付费，不用不占地方。**

> **前端类比：** 这就像 Vue Router 的路由懒加载（`() => import('./About.vue')`）——不把所有页面打包进首屏，只有访问到对应路由时才加载那个 chunk。Skills 的按需加载和这个思路一模一样：启动时只加载"路由表"（name + description），访问时才加载"页面组件"（SKILL.md 正文 + 附件）。

### 3.6 上下文压缩时的行为

Claude Code 有上下文压缩机制——当对话太长，它会压缩旧消息来腾空间。这时候 CLAUDE.md 和 Skills 的行为不同：

- **CLAUDE.md**：压缩后会重新读取，永远在上下文里。它是"常驻信息"，压缩不掉。
- **Skills**：压缩后会重新注入被调用过的 Skill，但有 token 预算上限。如果加载的 Skill 太多，最旧的会被踢掉。

这意味着：如果你一次对话里调用了 5 个 Skill，上下文爆了触发压缩，Claude 会保留最近用到的 Skill 内容，把最早用到的踢出去。CLAUDE.md 则不受影响——它是"压不掉的常驻信息"。

```
上下文压缩时：
┌────────────────────────────────────┐
│  CLAUDE.md        → 重新读取，永远在 │
│  最近的 Skill     → 保留             │
│  最旧的 Skill     → 被踢掉           │
└────────────────────────────────────┘
```

> **实践建议：** 别在一个 Skill 里塞太多文件。Skill 的 token 预算是有限的，文件太多会导致加载后撑爆上下文，或者压缩时被过早踢掉。一个 Skill 聚焦一类任务，文件控制在 3-5 个以内。

---

## 四、Skill vs CLAUDE.md vs Subagents 选型

### 4.1 三种"给 Agent 加能力"的方式

到今天为止，你已经学了三种"给 Claude Code 加能力"的方式：CLAUDE.md、Skills、Subagents。它们都能让 Agent 变强，但机制和适用场景完全不同。选错了，要么 token 浪费，要么上下文污染。

对比表：

| 方法 | 加载时机 | 占 token | 隔离性 | 适合 |
|------|---------|---------|--------|------|
| CLAUDE.md | 全程 | 高 | 无 | 事实信息（构建命令、目录结构） |
| Skills | 按需 | 低 | 无（主线程） | 流程步骤（审查流程、部署清单） |
| Subagents | 按需 | 零（对主上下文） | 有（独立上下文） | 脏活累活（搜索、日志分析） |

### 4.2 选型规则

三条规则，记住就行：

1. **需要随时知道的事实 → CLAUDE.md**
   - 例子：项目用 pnpm、后端在 8000 端口、目录结构约定、代码规范
   - 特征：每轮对话都可能用到，必须常驻

2. **需要按步骤执行的流程 → Skill**
   - 例子：代码审查 7 步流程、部署前检查清单、PR 模板生成流程
   - 特征：只有特定任务才用，用完可以"收起来"

3. **需要做大量中间步骤但不污染主上下文 → Subagent**
   - 例子：全仓库搜索某个 pattern、分析几千行日志、跑测试套件
   - 特征：中间过程又长又脏，只要最终结论

### 4.3 决策树

```
你要给 Agent 加的东西是什么？
│
├─ 事实信息（构建命令/目录/规范）
│   └─► CLAUDE.md
│       理由：随时要用，必须常驻
│
├─ 流程步骤（审查/部署/生成清单）
│   └─► Skill
│       理由：按需加载，用完收起，不常驻
│
└─ 大量中间操作（搜索/分析/跑测试）
    └─► Subagent
        理由：中间过程脏，隔离执行只回传结论
```

### 4.4 一个项目里三者共存的真实样子

一个真实的工程项目里，这三种方式是共存的。比如一个全栈项目：

```
my-project/
├── CLAUDE.md              ← 全局事实：pnpm、端口、目录结构
├── .claude/
│   ├── skills/
│   │   ├── code-review/    ← Skill：代码审查流程
│   │   ├── deploy-check/   ← Skill：部署前检查清单
│   │   └── pr-template/    ← Skill：生成 PR 描述
│   └── agents/
│       ├── log-analyzer.md ← Subagent：日志分析（脏活）
│       └── repo-search.md  ← Subagent：全仓库搜索（脏活）
```

- 你问"这个项目怎么启动" → Claude 读 CLAUDE.md 回答（常驻事实）
- 你说"帮我审查 auth.py" → 触发 code-review Skill（按需流程）
- 你说"搜一下所有用了 eval 的地方" → 派 repo-search Subagent（隔离脏活）

三者各司其职，没有谁替代谁。

---

## 动手实验

### 🟢 青铜：创建一个最小 SKILL.md

在 `.claude/skills/` 目录下创建一个最小的 Skill，只包含 `name` 和 `description`，正文随便写两步。

```
.claude/skills/
└── commit-helper/
    └── SKILL.md
```

`SKILL.md` 内容：

```markdown
---
name: commit-helper
description: 根据代码改动生成规范的 commit message
---

# Commit Message 生成流程

## 步骤
1. 用 git diff 查看当前改动
2. 根据 conventional commits 规范生成 message

## 验收标准
- message 格式为 type(scope): description
- type 在 feat/fix/docs/refactor 之一
```

做完后启动 Claude Code，观察它有没有发现这个 Skill（输入 `/` 看斜杠命令列表）。

### 🟡 白银：完成 skill_analysis.md

写一份分析文档 `skill_analysis.md`，对比 Skill / Tool / MCP / Prompt 四个概念的差异。要求：

1. 列出四个概念各自的本质（一句话）
2. 画一个四概念在同一任务里分工的 ASCII 图
3. 解释 Week 07 Skills 和 Claude Code Skills 的区别
4. 给出一个"什么场景该用哪个"的选型表

把文档放到 `e:\workspace\project\myAIAgentLearning\week08\day03\skill_analysis.md`。这是本周 Day 03 的正式产出物（day01-07.md 里列了）。

### 🔴 王者：在 Claude Code 中实际触发一个 Skill

在 Claude Code 中实际触发一个 Skill，观察加载过程：

1. 创建一个 Skill（可以用青铜实验那个，或自己写个更完整的）
2. 启动 Claude Code，输入 `/` 查看是否能发现你的 Skill
3. 用斜杠命令触发它（比如 `/commit-helper`）
4. 观察触发后 Claude 的行为：它是不是按照 SKILL.md 里的步骤执行？
5. 记录观察到的现象：加载前后 token 变化、执行过程是否可见

把观察记录写进 `skill_analysis.md` 的最后一节"实战观察"。

> **提示：** 如果你的 Claude Code 版本不支持 Skills，就只做青铜和白银。王者实验需要 Claude Code 较新版本。观察的重点是"按需加载"——触发前 Claude 只知道 Skill 的名字和描述，触发后才按步骤执行。

---

## 踩坑记录 🕳️

### 坑 1：把 system_prompt 塞进 SKILL.md

最常见的错误。有人把整个 system_prompt（"你是一个资深代码审查专家，你有 10 年经验，你擅长..."）原封不动塞进 SKILL.md 正文，以为这就是 Skill。

**问题：** system_prompt 是"定义 Agent 身份"的，应该放在 Agent 创建时或 CLAUDE.md 里。SKILL.md 正文应该是"流程步骤"——做什么、怎么做、验收标准是什么。身份定义和流程定义是两码事。

**解决：** SKILL.md 正文写"步骤 + 验收标准"，别写"你是谁"。身份类信息放 CLAUDE.md。

### 坑 2：SKILL.md 的 frontmatter 格式不规范

frontmatter 必须是规范的 YAML，用 `---` 包裹。常见错误：

```yaml
# 错误：少了结尾的 ---
---
name: code-review
description: 代码审查
# 这里少了 ---

# 错误：用了中文 key
---
名称: code-review
描述: 代码审查
---

# 错误：description 写成多行但没有正确缩进
---
name: code-review
description: 对代码进行全面审查
检查安全、性能、可维护性
---
```

**解决：** 严格用 `name` 和 `description` 两个英文 key，description 如果很长就用引号包起来或者写一行。frontmatter 必须以 `---` 开头和结尾。

### 坑 3：一个 Skill 里塞太多文件

有人觉得"既然 Skill 是能力包，那我把所有模板、所有脚本、所有清单都塞进去"。结果一个 Skill 文件夹里有 20 个文件，加载时直接撑爆上下文预算。

**问题：** Skills 有 token 预算上限。文件太多，加载后要么超预算被截断，要么压缩时被过早踢掉。

**解决：** 一个 Skill 聚焦一类任务，文件控制在 3-5 个以内。如果有更多内容，拆成多个 Skill。比如不要把"代码审查 + 部署检查 + 测试生成"塞一个 Skill，拆成三个：`code-review/`、`deploy-check/`、`test-gen/`。

### 坑 4：混淆 Week 07 Skills 和 Claude Code Skills

面试时说"我学过 Skills"，面试官问"哪种 Skills？"，你答不上来。Week 07 的 Skills 是 LangChain 的 `load_skill` 工具（加载一段 prompt 文本），Claude Code 的 Skills 是一个能力包文件夹（含 SKILL.md + 脚本 + 模板）。名字一样，概念不同。

**解决：** 面试时主动说清楚："Week 07 的 LangChain Skills 是单 Agent 框架内的动态知识加载工具；Claude Code 的 Skills 是可发现、可版本化的能力包文件夹。两者名字相同但概念不同。"这样不仅不踩坑，还显得你理解得深。

---

## 副线笔记

### 阅读 Claude Code 官方 Skills 文档

官方文档地址：https://claude.com/blog/complete-guide-to-building-skills-for-claude

建议重点看这几部分：

1. SKILL.md 的完整字段说明（除了 name/description 还有什么字段）
2. Skill 的发现机制（Claude 怎么扫描和匹配 Skill）
3. Skill 和 CLAUDE.md、Subagents 的官方推荐用法
4. 实际案例（官方示例 Skill 长什么样）

### 对比不同工具的"能力复用"方案

Skills 不是唯一解决"能力复用"的方案。对比一下三大 AI 编程工具的做法：

| 工具 | 能力复用方案 | 形态 | 加载机制 |
|------|-------------|------|---------|
| Claude Code | Skills | `.claude/skills/` 文件夹 | 按需加载 frontmatter |
| Cursor | Rules | `.cursorrules` 文件 | 全程加载 |
| Aider | Conventions | `.aider.conf.yml` | 配置式 |

三种方案的共同点：都是"把可复用的知识/规范固化成文件"。差异在于加载策略和粒度——Cursor 的 Rules 是全程加载（类似 CLAUDE.md），Claude Code 的 Skills 是按需加载（更省 token）。

> **思考题：** 为什么 Cursor 选全程加载的 Rules，而 Claude Code 选按需加载的 Skills？提示：和两个产品的交互模式有关——Cursor 偏"编辑器内持续对话"，Claude Code 偏"任务驱动的命令行"。

---

## 检查清单

- [ ] 理解 Skills 是能力包而非提示词——Skill 是文件夹（SKILL.md + 脚本 + 模板），不是一段文本
- [ ] 能区分 Skill / Tool / MCP / Prompt 四个概念，说出各自的"比喻"（手/嘴/神经接口/大脑的知识）
- [ ] 理解按需加载机制——启动时只读 name + description（几十 token），调用时才加载完整内容
- [ ] 知道 Week 07 的 LangChain Skills（load_skill 工具）和 Claude Code Skills（能力包文件夹）是不同概念
- [ ] 能说出 CLAUDE.md、Skills、Subagents 三者的选型规则（事实/流程/脏活）
- [ ] 理解 Skills 在主线程执行（过程可见）vs Subagents 在独立上下文执行（只回传结论）
- [ ] 完成了 skill_analysis.md 四概念对比文档

---

## 下课预告

> **Day 04 — SKILL.md 实战：写一个可复用能力包。** 今天我们搞清楚了 Skills 是什么、和 Tool/MCP/Prompt 的区别、按需加载机制。明天就动手写一个完整的 SKILL.md——包含 name、description、流程步骤、验收标准，还挂一个辅助脚本和一个模板文件。你会真正在 Claude Code 里触发它，观察"从扫描发现到按需加载到按步骤执行"的完整链路。副线对比 CLAUDE.md 和 Skills 在同一个项目里怎么分工——哪些信息该常驻，哪些该按需。这是本周的核心产出，Day 07 的综合项目会用到你 Day 04 写的这个 Skill。
