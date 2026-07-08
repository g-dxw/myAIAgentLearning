# Day 07 — 综合产出：自定义 MCP Server + Skill

## 今日目标

把本周六天学的全部组装成一个**完整的能力包**——一个能接入 Claude Code、让它变成"徒步路线评估助手"的能力包。

过去六天我们一天搭一块拼图：Day 01-02 写了 MCP Server，暴露 Tool / Resource / Prompt 三种能力；Day 03-04 学了 Skills，写了带 frontmatter + 辅助脚本的 SKILL.md；Day 05 学了 A2A / ACP，知道 Agent 之间怎么跨框架通信；Day 06 打开了 MCP Client 的黑盒，亲手写了"连接 → 发现 → 调用 → 返回"的完整链路。今天把这几块拼成一个整体：MCP Server 出工具、SKILL.md 出流程、MCP Client 出连接，三者在 Claude Code 这个 Host 里协作。

**今天全程 Claude Code 结对编程。** 你做架构决策（哪些工具、Skill 写什么流程、Client 怎么验证），Claude Code 出第一版代码，你审查修改。最后用自然语言在 Claude Code 里实测，让 Claude 自己决定调用哪个工具、何时触发 Skill。

**产出目标：**

1. 一个徒步路线评估 MCP Server（暴露 Tool + Resource + Prompt）
2. 一个 route-assessment Skill（定义路线风险评估的完整流程）
3. 一个 MCP Client（连接 Server 并发现工具）
4. 接入 Claude Code 验证，用自然语言触发工具和 Skill

---

## 项目定位

```
一个徒步路线评估能力包，包含：
1. MCP Server：暴露路线搜索(Tool) + 路线配置(Resource) + 评估提示词(Prompt)
2. Skill：route-assessment，定义路线风险评估的完整流程
3. MCP Client：连接 Server 并发现工具

这个能力包可以接入 Claude Code，让 Claude Code 变成徒步路线评估助手。
```

> **和 Week 07 Day 07 的多 Agent 系统对比：** Week 07 用 LangGraph `create_agent` + Subagents 在框架内构建多 Agent 系统，工具是 `@tool` 装饰的 Python 函数，跑在同一个进程里。Week 08 把工具抽出来变成 MCP Server——跨进程、跨语言，任何 MCP Client 都能用。Week 07 的"能力"是"框架内函数"，Week 08 的"能力"是"标准化服务 + 可复用流程"。核心升级是**标准化**——MCP 让工具跨进程，A2A 让 Agent 跨框架，Skills 让能力可复用。

| 维度 | Week 07 Day 07 | Week 08 Day 07 |
|------|----------------|----------------|
| 工具形态 | `@tool` Python 函数（同进程） | MCP Server 暴露的远程能力（跨进程） |
| 流程知识 | 写在 Agent 的 system_prompt 里 | 独立的 SKILL.md 文件，按需加载 |
| 客户端 | LangGraph 自带的 Agent runtime | MCP Client + Claude Code Host |
| 复用范围 | 只能在这个 LangGraph 项目里用 | 任何 MCP Client 都能用（Claude Code / Cursor / 自写 Host） |
| 部署方式 | 一个 FastAPI 服务 | Server + Skill + Client 三个独立组件 |

---

## 项目结构

```
week08/day07/
├── mcp_server/
│   ├── __init__.py
│   ├── server.py          # MCP Server 入口（Tool + Resource + Prompt）
│   ├── tools.py            # 工具定义（路线搜索/天气查询/难度评估）
│   └── data.py             # 路线数据库（mock 数据）
├── skill/
│   └── route-assessment/
│       ├── SKILL.md        # 路线评估流程定义
│       ├── checklist.md     # 风险检查清单
│       └── grade.py         # 难度评级辅助脚本
├── client/
│   └── mcp_client.py       # MCP Client + 工具发现
├── config/
│   └── claude_code_config.json  # Claude Code 接入配置
└── README.md
```

这个结构和 Day 02 的单文件 `my_mcp_server.py`、Day 04 的单文件夹 Skill、Day 06 的单文件 Client 都不一样。今天按"项目"的标准来组织——Server 拆成 `server.py`（入口）/ `tools.py`（工具实现）/ `data.py`（数据），因为工具多了之后全塞在 server.py 里会变成"面条代码"。Skill 单独一个 `skill/` 目录，里面挂 `checklist.md`（风险检查清单）和 `grade.py`（评级脚本）两个附件——Day 04 讲过，Skill 是"工具箱"不是"纸条"，附件才是它的价值。

---

## 架构设计

### 整体架构图

```
┌──────────────────────────────────────────────────┐
│            Claude Code (MCP Host)                │
│                                                  │
│  ┌──────────┐   ┌──────────────────────────┐    │
│  │   LLM    │   │ Skill: route-assessment  │    │
│  │          │   │ (按需加载评估流程)        │    │
│  └──────────┘   └──────────────────────────┘    │
│       ↕                                          │
│  ┌──────────────────┐                            │
│  │   MCP Client     │                            │
│  └────────┬─────────┘                            │
└───────────┼──────────────────────────────────────┘
            │ stdio
            ▼
┌───────────────────────────────┐
│    Hiking MCP Server          │
│                               │
│  Tools:                       │
│  - search_routes              │
│  - get_route_detail           │
│  - assess_difficulty          │
│                               │
│  Resources:                   │
│  - route://database           │
│  - route://safety-rules       │
│                               │
│  Prompts:                     │
│  - route_assessment            │
└───────────────────────────────┘
```

### 三层职责划分

整个能力包分三层，每层职责单一、互不越界。这是今天架构设计的核心：

| 层 | 组件 | 职责 | 不做什么 |
|----|------|------|---------|
| 接口层 | MCP Server | 暴露工具/资源/提示词，提供"能力" | 不写业务流程，不决定调用顺序 |
| 知识层 | SKILL.md | 定义评估流程，提供"怎么用能力" | 不实现工具，不连 Server |
| 连接层 | MCP Client | 连接 Server，发现并转发调用 | 不做业务判断，不写流程 |

这三层对应 Day 03 讲的"Skill vs Tool vs MCP vs Prompt"四个概念里的三个——Skill（知识层）、MCP（接口层 + 连接层）。Prompt 在本项目里是接口层的一部分（挂在 Server 上），不是独立一层。

```
用户在 Claude Code 输入："评估一下长穿毕路线的风险"
  │
  ▼
┌─────────────────────────────────────────────────┐
│ Claude Code (Host)                              │
│                                                 │
│ 1. LLM 看到用户意图 → 匹配 Skill description     │
│    → 触发 route-assessment Skill                 │
│                                                 │
│ 2. Skill 加载正文 → 读到"调用 search_routes       │
│    → get_route_detail → assess_difficulty"      │
│                                                 │
│ 3. LLM 按 Skill 步骤调工具 → Client 转发         │
└─────────────────┬───────────────────────────────┘
                  │
                  ▼
         Hiking MCP Server
         执行 search_routes → 返回路线列表
         执行 get_route_detail → 返回详细信息
         执行 assess_difficulty → 返回难度评级
                  │
                  ▼
         LLM 综合结果 → 按 Skill 验收标准输出报告
```

### 为什么这么分层

很多人第一次做这种项目会犯一个错：把流程写在 Server 里。比如在 `assess_difficulty` 工具里直接调 `get_route_detail`，让一个工具干两件事。这违背了 Day 02 讲的"Tool 单一职责"原则——Tool 是"动词"，一个动词干一件事。

正确的做法是：Server 只提供原子能力（搜路线、查详情、评难度），流程编排由 Skill 来做。Skill 说"先搜、再查、再评"，LLM 按 Skill 的步骤逐个调用工具。这样 Server 的工具能被不同 Skill 复用——今天有 `route-assessment`，明天加个 `route-comparison`（路线对比），Server 的工具一行都不用改。

> **前端类比：** Server 像 REST API（提供端点），Skill 像前端业务逻辑（编排 API 调用顺序）。你不会在后端 API 里写"先调 A 再调 B 再调 C"的业务流程——那是前端的活。MCP Server 和 SKILL.md 的分工也是这个道理。

### Skill 触发机制回顾

Day 03-04 讲过 Skill 的"按需加载"：Claude Code 启动时只读 SKILL.md 的 frontmatter（`name` + `description`，几十 token），用户说话时 Claude 靠 `description` 判断要不要触发这个 Skill。所以 `description` 写得好不好，直接决定 Skill 会不会被调用。

```
Claude Code 启动：
  扫描 .claude/skills/ → 发现 route-assessment/
  只读 SKILL.md 的 frontmatter：
    name: route-assessment
    description: 对徒步路线进行全面风险评估...
  → 记住"有这个能力"，正文不加载

用户输入："评估一下长穿毕路线的风险"
  Claude 判断：这句话匹配 route-assessment 的 description
  → 触发 Skill → 加载 SKILL.md 正文 → 按步骤调用 MCP 工具
```

| 描述写法 | 触发率 | 问题 |
|---------|--------|------|
| `路线评估` | 低 | 太短，Claude 不知道评估什么、什么时候用 |
| `对徒步路线进行全面风险评估，包含难度、季节、风险点、装备、应急方案` | 高 | 说清"做什么 + 什么时候用" |
| `一个能力包` | 几乎不触发 | 完全没说干什么 |

---

## 代码实现

### mcp_server/data.py — 路线数据库

先把数据层独立出来。Day 02 我们把 mock 数据塞在 server.py 里，今天按项目标准拆出去——数据是数据，逻辑是逻辑。

```python
"""mcp_server/data.py — 路线数据库 + 安全规则

mock 数据，实际项目替换为数据库查询或向量库检索。
数据结构参考 CMA 山地户外教练的路线档案标准。
"""

# 徒步路线数据库
ROUTE_DATABASE = [
    {
        "name": "长穿毕（长坪沟穿越毕棚沟）",
        "difficulty": "进阶",
        "days": 4,
        "elevation": 4668,
        "distance": 45,
        "region": "川西",
        "highlights": "经典穿越路线，雪山草甸海子一网打尽",
        "risks": "翻越垭口海拔高、夜间低温、涉水路段",
        "gear": "登山鞋、双杖、冲锋衣、睡袋-10°C、防潮垫",
        "best_season": "6-10月",
        "rescue": "毕棚沟景区救援点，约6小时下撤",
    },
    {
        "name": "四姑娘山二峰",
        "difficulty": "硬核",
        "days": 3,
        "elevation": 5276,
        "distance": 30,
        "region": "川西",
        "highlights": "蜀山之后，技术攀登入门级雪峰",
        "risks": "高海拔缺氧、雪崩风险、技术路段",
        "gear": "高山靴、冰爪、头盔、安全带、主锁、扁带",
        "best_season": "5-9月",
        "rescue": "大本营救援，需协作下撤，约8小时",
    },
    {
        "name": "贡嘎大环线",
        "difficulty": "硬核",
        "days": 7,
        "elevation": 4920,
        "distance": 78,
        "region": "川西",
        "highlights": "蜀山之王环绕，冰川全景",
        "risks": "高反、长途负重、天气多变、渡河",
        "gear": "全套装备、卫星电话、PLB、雪套、冰爪",
        "best_season": "7-9月",
        "rescue": "救援困难，最近点需徒步2天出山",
    },
    {
        "name": "雨崩徒步",
        "difficulty": "进阶",
        "days": 5,
        "elevation": 3900,
        "distance": 40,
        "region": "云南",
        "highlights": "梅里雪山脚下，神瀑冰湖",
        "risks": "高反、雨后路滑、迷路岔路",
        "gear": "登山鞋、双杖、雨衣、保暖层",
        "best_season": "4-6月、9-11月",
        "rescue": "雨崩村救援点，约4小时下撤",
    },
    {
        "name": "九顶山",
        "difficulty": "休闲",
        "days": 2,
        "elevation": 3400,
        "distance": 15,
        "region": "川西",
        "highlights": "高山草甸花海，周末轻徒步",
        "risks": "天气突变、紫外线强",
        "gear": "登山鞋、登山杖、防晒、保暖层",
        "best_season": "6-8月花季",
        "rescue": "景区救援，约2小时下撤",
    },
    {
        "name": "冈仁波齐转山",
        "difficulty": "硬核",
        "days": 3,
        "elevation": 5650,
        "distance": 53,
        "region": "西藏",
        "highlights": "世界中心神山转山",
        "risks": "极高海拔、缺氧、低温、长途无补给",
        "gear": "高山靴、羽绒、氧气瓶、卫星电话",
        "best_season": "5-9月",
        "rescue": "塔钦救援点，转山途中需自行下撤",
    },
]

# 安全规则（作为 Resource 暴露）
SAFETY_RULES = """# 徒步安全规则（CMA 山地户外教练标准）

## 出发前
1. 向家人/朋友报备路线和预计返回时间
2. 检查装备完整性，特别是通讯和导航设备
3. 确认天气预报，避开恶劣天气窗口
4. 购买户外保险（高海拔路线需含高反险）

## 行进中
1. 保持队形，前后队员保持视线或对讲机联系
2. 每30分钟主动补水，每1小时补充能量
3. 高海拔路线注意节奏，出现头痛/恶心立即停止上升
4. 垭口/悬崖路段单人通过，不抢行

## 应急
1. 高反：立即停止上升，症状不缓解则下撤
2. 失温：立即停止行进，换干衣，补充热饮
3. 迷路：原地停留，使用哨子/卫星电话求救
4. 受伤：评估伤情，轻伤自理，重伤原地等待救援

## 通讯盲区标注
- 川西垭口段：多数无信号
- 贡嘎大环线：全程基本无信号
- 雨崩：村内有信号，途中无
- 冈仁波齐：转山途中无信号
"""
```

### mcp_server/tools.py — 工具实现

工具逻辑也独立出来。每个工具做一件事，不互相调用——流程编排是 Skill 的活，不是工具的活。

```python
"""mcp_server/tools.py — 工具实现

三个工具各自独立，不互相调用。
流程编排（先搜再查再评）由 SKILL.md 定义，由 LLM 执行。
"""
from mcp_server.data import ROUTE_DATABASE


async def search_routes(difficulty: str = "", days: int = 0, region: str = "") -> str:
    """搜索徒步路线。

    Args:
        difficulty: 难度（休闲/进阶/硬核），可选
        days: 天数，可选，传0表示不筛选
        region: 区域（川西/云南/西藏），可选
    """
    results = []
    for route in ROUTE_DATABASE:
        if difficulty and route["difficulty"] != difficulty:
            continue
        if days and route["days"] != days:
            continue
        if region and route["region"] != region:
            continue
        results.append(
            f"- {route['name']}（{route['difficulty']}/"
            f"{route['days']}天/{route['region']}）"
        )
    return "\n".join(results) if results else "未找到匹配路线"


async def get_route_detail(route_name: str) -> str:
    """获取路线详细信息。

    Args:
        route_name: 路线名称（需与数据库中的名称完全匹配）
    """
    for route in ROUTE_DATABASE:
        if route["name"] == route_name or route_name in route["name"]:
            return f"""路线：{route['name']}
难度：{route['difficulty']}
天数：{route['days']}天
海拔：{route['elevation']}m
距离：{route['distance']}km
区域：{route['region']}
亮点：{route['highlights']}
风险：{route['risks']}
装备建议：{route['gear']}
最佳季节：{route['best_season']}
救援：{route['rescue']}"""
    return f"未找到路线：{route_name}"


async def assess_difficulty(route_name: str) -> str:
    """评估路线难度等级。

    基于 CMA 山地户外难度分级标准：
    - 海拔 >4000m 加3分，>3000m 加2分
    - 距离 >50km 加3分，>30km 加2分
    - 天数 >5天 加2分
    - 总分 >=7 硬核，>=4 进阶，<4 休闲

    Args:
        route_name: 路线名称
    """
    for route in ROUTE_DATABASE:
        if route["name"] == route_name or route_name in route["name"]:
            score = 0
            alt_score = 3 if route["elevation"] > 4000 else 2 if route["elevation"] > 3000 else 0
            dist_score = 3 if route["distance"] > 50 else 2 if route["distance"] > 30 else 0
            day_score = 2 if route["days"] > 5 else 0
            score = alt_score + dist_score + day_score
            level = "硬核" if score >= 7 else "进阶" if score >= 4 else "休闲"
            return f"""难度评估：{level}（得分 {score}/10）

评分明细：
- 海拔 {route['elevation']}m → +{alt_score} 分
- 距离 {route['distance']}km → +{dist_score} 分
- 天数 {route['days']}天 → +{day_score} 分

参考标准：CMA 山地户外难度分级"""
    return f"未找到路线：{route_name}"
```

### mcp_server/server.py — MCP Server 入口

把 tools.py 的函数注册成 MCP 工具，再暴露 Resource 和 Prompt。这里用 `@server.tool()` 装饰器把独立函数包装成 MCP 工具。

```python
"""mcp_server/server.py — MCP Server 入口

暴露三种能力：
1. Tool: search_routes, get_route_detail, assess_difficulty
2. Resource: route://database, route://safety-rules
3. Prompt: route_assessment

运行方式：python -m mcp_server.server
或被 Client 通过 stdio 启动。
"""
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
from mcp_server.data import ROUTE_DATABASE, SAFETY_RULES
from mcp_server.tools import search_routes, get_route_detail, assess_difficulty

server = Server("hiking-route-server")


# ─── Tools ───
@server.tool()
async def search_routes_tool(difficulty: str = "", days: int = 0, region: str = "") -> str:
    """搜索徒步路线。

    可按难度（休闲/进阶/硬核）、天数、区域（川西/云南/西藏）筛选。
    所有参数可选，不传则返回全部路线。

    Args:
        difficulty: 难度筛选，可选值：休闲/进阶/硬核
        days: 天数筛选，传0或不传表示不筛选
        region: 区域筛选，可选值：川西/云南/西藏
    """
    return await search_routes(difficulty, days, region)


@server.tool()
async def get_route_detail_tool(route_name: str) -> str:
    """获取指定路线的详细信息。

    包含海拔、距离、天数、风险、装备建议、最佳季节、救援点等。
    route_name 支持模糊匹配（如传"长穿毕"可匹配"长穿毕（长坪沟穿越毕棚沟）"）。

    Args:
        route_name: 路线名称，支持模糊匹配
    """
    return await get_route_detail(route_name)


@server.tool()
async def assess_difficulty_tool(route_name: str) -> str:
    """评估路线难度等级。

    基于海拔、距离、天数综合评分，参考 CMA 山地户外难度分级标准。
    输出难度等级（休闲/进阶/硬核）和得分明细。

    Args:
        route_name: 路线名称
    """
    return await assess_difficulty(route_name)


# ─── Resources ───
@server.resource("route://database")
async def get_route_database() -> str:
    """路线数据库（只读资源）"""
    lines = ["# 徒步路线数据库", ""]
    for r in ROUTE_DATABASE:
        lines.append(
            f"- {r['name']}（{r['difficulty']}/{r['days']}天/"
            f"{r['elevation']}m/{r['region']}）"
        )
    return "\n".join(lines)


@server.resource("route://safety-rules")
async def get_safety_rules() -> str:
    """安全规则（只读资源）"""
    return SAFETY_RULES


# ─── Prompts ───
@server.prompt()
async def route_assessment(route_name: str) -> str:
    """路线评估提示词模板

    生成一个完整的路线评估指令，包含5个评估维度。
    适合在评估某条路线时使用。

    Args:
        route_name: 要评估的路线名称
    """
    return f"""你是 CMA 山地户外教练。请对以下路线做全面评估：

路线：{route_name}

评估维度：
1. 难度评估（海拔、距离、天数综合评级）
2. 季节适宜性（最佳季节和不宜季节）
3. 风险点（落石、高反、涉水、迷路等）
4. 装备建议（必备/推荐/可选）
5. 应急方案（下撤路线、最近救援点、通讯盲区）

输出格式：Markdown 报告，每个维度一个章节。
高风险路线在标题前标注 [警告]。
"""


if __name__ == "__main__":
    import asyncio
    asyncio.run(stdio_server(server))
```

> **关键点：tool 函数的 docstring 决定 LLM 何时调用。** Day 02 和 Day 06 都踩过这个坑——docstring 写得模糊，LLM 不知道什么时候调。这里的 docstring 明确写了"可按难度/天数/区域筛选""支持模糊匹配""参考 CMA 标准"，让 LLM 一眼就知道这个工具能干什么、参数怎么填。

### SKILL.md — 路线评估流程定义

Skill 是"知识层"，定义"怎么用 Server 提供的工具完成路线评估"。注意 frontmatter 的 `description`——这是 Skill 能否被触发的命脉。

```markdown
---
name: route-assessment
description: 对徒步路线进行全面风险评估，包含难度评级、季节适宜性、风险点、装备建议和应急方案。当用户要求评估某条徒步路线的风险、安全性、难度时使用此 Skill。
---

# 徒步路线评估流程

## 何时使用
- 用户要求评估某条徒步路线时
- 出行前的路线风险评估
- 选择路线时的对比评估
- 用户问"这条路线安全吗""难度怎么样""需要带什么"

## 步骤

### 1. 获取路线信息
- 调用 search_routes 找到目标路线（支持模糊搜索）
- 调用 get_route_detail 获取详细信息（海拔/距离/风险/装备/救援点）
- 调用 assess_difficulty 获取难度评级

### 2. 难度评估
- 综合海拔、距离、天数
- 参考 CMA 山地户外难度分级标准
- 输出难度等级（休闲/进阶/硬核）和得分依据

### 3. 风险识别
- 高海拔风险（高反、缺氧、低温）
- 地形风险（落石、悬崖、涉水、技术路段）
- 天气风险（突降雨雪、低温、大风）
- 迷路风险（路迹清晰度、岔路密度）

### 4. 装备建议
- 必备：登山鞋、背包、急救包、头灯、通讯设备
- 推荐：登山杖、护膝、对讲机、冲锋衣（按难度调整）
- 可选：GPS、卫星电话、PLB（按风险调整）

### 5. 应急方案
- 下撤路线（最近的撤离点）
- 最近救援点（距离和预计时间）
- 通讯盲区标注（参考 route://safety-rules 资源）

## 验收标准
- [ ] 输出 Markdown 格式的评估报告
- [ ] 包含全部 5 个评估维度
- [ ] 难度评级有依据（引用 assess_difficulty 的得分）
- [ ] 装备建议分级（必备/推荐/可选）
- [ ] 应急方案包含下撤路线和救援点
- [ ] 高风险路线（硬核级）在标题标注 [警告]

## 约束
- 基于 MCP Server 的数据评估，不编造信息
- 如果路线不在数据库中，如实告知用户
- 高风险路线必须标红警告
- 装备建议参考 get_route_detail 返回的 gear 字段，不自行编造
- 评估报告参考 route_assessment Prompt 的格式
```

### skill/route-assessment/checklist.md — 风险检查清单

Day 04 讲过，Skill 是"工具箱"，附件是它的价值。这个 checklist 是 SKILL.md 引用的辅助文件，按维度列出具体检查项。

```markdown
# 徒步路线风险检查清单

评估路线时逐项检查，每项标注 [通过] / [警告] / [不适用]。

## 海拔风险
- [ ] 海拔是否 >4000m？（高反风险）
- [ ] 是否有快速爬升段（单日上升 >1000m）？
- [ ] 是否有队员无高海拔经验？
- [ ] 是否准备氧气/高反药？

## 地形风险
- [ ] 是否有悬崖/落石路段？
- [ ] 是否有涉水路段？（雨季水位变化）
- [ ] 是否有技术攀登段？（需绳索/保护）

## 天气与迷路
- [ ] 是否查过近期天气预报？是否在雨季/雪季？
- [ ] 垭口风力是否 >6级？是否有突降雨雪可能？
- [ ] 路迹是否清晰？是否有频繁岔路？
- [ ] 是否有离线地图/GPS？是否有熟悉路线的向导？

## 补给与通讯
- [ ] 全程是否有补给点？通讯盲区是否标注？
- [ ] 是否携带卫星电话/PLB？应急下撤路线是否明确？
```

### skill/route-assessment/grade.py — 难度评级辅助脚本

评级脚本，独立于 MCP Server 运行，用于 Skill 外的快速评级。也可以被 SKILL.md 引用作为评级逻辑的参考实现。

```python
"""skill/route-assessment/grade.py — 难度评级辅助脚本

独立运行，用于快速评级。
评分规则与 mcp_server/tools.py 的 assess_difficulty 一致，
但这里做成可独立调用的命令行工具。

用法：
    python grade.py --name "长穿毕"
    python grade.py --altitude 4668 --distance 45 --days 4
"""
import argparse


def grade_route(altitude: int, distance: int, days: int) -> tuple[str, int, dict]:
    """根据海拔、距离、天数评级。

    Returns:
        (level, score, detail)
        level: 休闲/进阶/硬核
        score: 总分（满分10）
        detail: 各项得分明细
    """
    alt_score = 3 if altitude > 4000 else 2 if altitude > 3000 else 0
    dist_score = 3 if distance > 50 else 2 if distance > 30 else 0
    day_score = 2 if days > 5 else 0
    score = alt_score + dist_score + day_score
    level = "硬核" if score >= 7 else "进阶" if score >= 4 else "休闲"
    detail = {
        "海拔": f"{altitude}m → +{alt_score}",
        "距离": f"{distance}km → +{dist_score}",
        "天数": f"{days}天 → +{day_score}",
    }
    return level, score, detail


# 路线名 → 参数（与 data.py 保持一致）
ROUTE_MAP = {
    "长穿毕": {"altitude": 4668, "distance": 45, "days": 4},
    "四姑娘山二峰": {"altitude": 5276, "distance": 30, "days": 3},
    "贡嘎大环线": {"altitude": 4920, "distance": 78, "days": 7},
    "雨崩徒步": {"altitude": 3900, "distance": 40, "days": 5},
    "九顶山": {"altitude": 3400, "distance": 15, "days": 2},
    "冈仁波齐转山": {"altitude": 5650, "distance": 53, "days": 3},
}


def main():
    parser = argparse.ArgumentParser(description="徒步路线难度评级工具")
    parser.add_argument("--name", type=str, help="路线名称（如 长穿毕）")
    parser.add_argument("--altitude", type=int, help="海拔（米）")
    parser.add_argument("--distance", type=int, help="距离（公里）")
    parser.add_argument("--days", type=int, help="天数")
    args = parser.parse_args()

    if args.name:
        params = ROUTE_MAP.get(args.name)
        if not params:
            # 模糊匹配
            matches = [k for k in ROUTE_MAP if args.name in k]
            if not matches:
                print(f"未找到路线：{args.name}")
                return
            params = ROUTE_MAP[matches[0]]
            print(f"匹配到：{matches[0]}")
    else:
        params = {
            "altitude": args.altitude or 0,
            "distance": args.distance or 0,
            "days": args.days or 0,
        }

    level, score, detail = grade_route(**params)
    print(f"\n难度评级：{level}（得分 {score}/10）\n")
    print("评分明细：")
    for key, val in detail.items():
        print(f"  - {key}: {val}")


if __name__ == "__main__":
    main()
```

### client/mcp_client.py — MCP Client + 工具发现

Day 06 写的 Client 是"纯发现"——只列工具不调 LLM。今天加一步：发现后实际调用工具，验证整条链路通不通。

```python
"""client/mcp_client.py — MCP Client + 工具发现 + 调用验证

连接 hiking-route-server，完整走一遍：
1. 连接（stdio 启动 Server 子进程）
2. 发现（list_tools / list_resources / list_prompts）
3. 调用（call_tool 验证工具能跑通）

运行方式：
    cd week08/day07
    python client/mcp_client.py
"""
import asyncio
from mcp.client import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters


async def main():
    # 1. 配置要连接的 MCP Server
    server_params = StdioServerParameters(
        command="python",
        args=["-m", "mcp_server.server"],
        env=None,  # 继承当前环境变量
    )

    print("=" * 60)
    print("连接 hiking-route-server...")
    print("=" * 60)

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # 2. 握手
            await session.initialize()
            print("握手完成，连接已建立\n")

            # 3. 发现工具
            print("=" * 60)
            print("发现工具 (tools/list)")
            print("=" * 60)
            tools = await session.list_tools()
            for t in tools.tools:
                print(f"  - {t.name}: {t.description[:50]}...")

            # 4. 发现资源
            print("\n" + "=" * 60)
            print("发现资源 (resources/list)")
            print("=" * 60)
            resources = await session.list_resources()
            for r in resources.resources:
                print(f"  - {r.uri}: {r.description}")

            # 5. 发现提示词
            print("\n" + "=" * 60)
            print("发现提示词 (prompts/list)")
            print("=" * 60)
            prompts = await session.list_prompts()
            for p in prompts.prompts:
                print(f"  - {p.name}: {p.description}")

            # 6. 调用工具：搜索进阶路线
            print("\n" + "=" * 60)
            print("调用工具: search_routes_tool")
            print("=" * 60)
            result = await session.call_tool(
                "search_routes_tool",
                arguments={"difficulty": "进阶"},
            )
            print(f"结果:\n{result.content[0].text}")

            # 7. 调用工具：获取长穿毕详情
            print("\n" + "=" * 60)
            print("调用工具: get_route_detail_tool")
            print("=" * 60)
            result = await session.call_tool(
                "get_route_detail_tool",
                arguments={"route_name": "长穿毕"},
            )
            print(f"结果:\n{result.content[0].text}")

            # 8. 调用工具：评估难度
            print("\n" + "=" * 60)
            print("调用工具: assess_difficulty_tool")
            print("=" * 60)
            result = await session.call_tool(
                "assess_difficulty_tool",
                arguments={"route_name": "长穿毕"},
            )
            print(f"结果:\n{result.content[0].text}")

            # 9. 读取资源：安全规则
            print("\n" + "=" * 60)
            print("读取资源: route://safety-rules")
            print("=" * 60)
            content = await session.read_resource("route://safety-rules")
            print(f"内容（前200字）:\n{content[:200]}...")

            print("\n" + "=" * 60)
            print("全部验证通过，能力包可接入 Claude Code")
            print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
```

### mcp_server/__init__.py — 包初始化

```python
"""mcp_server 包初始化"""
```

空文件即可，让 `mcp_server` 成为一个可导入的 Python 包。

### config/claude_code_config.json — Claude Code 接入配置

```json
{
  "mcpServers": {
    "hiking-routes": {
      "command": "python",
      "args": ["-m", "mcp_server.server"],
      "cwd": "e:/workspace/project/myAIAgentLearning/week08/day07"
    }
  }
}
```

> **注意：** Day 02 接入 Claude Code 时用的是相对路径 `args: ["week08/day07/mcp_server/server.py"]`，结果踩了"路径找不到"的坑。今天用 `-m mcp_server.server` 模块方式启动 + `cwd` 指定工作目录，更稳健。`-m` 让 Python 把 `mcp_server` 当包导入，`__init__.py` 和相对导入才能正确工作。

### README.md — 项目说明

```markdown
# 徒步路线评估能力包

一个可接入 Claude Code 的能力包，包含 MCP Server + Skill + Client。

## 组件
- `mcp_server/`：徒步路线 MCP Server（Tool + Resource + Prompt）
- `skill/route-assessment/`：路线评估 Skill（SKILL.md + checklist + grade.py）
- `client/mcp_client.py`：MCP Client（连接 + 发现 + 调用验证）
- `config/claude_code_config.json`：Claude Code 接入配置

## 快速开始

### 1. 安装依赖
\`\`\`bash
pip install mcp
\`\`\`

### 2. 测试 Client
\`\`\`bash
cd week08/day07
python client/mcp_client.py
\`\`\`

### 3. 接入 Claude Code
把 `config/claude_code_config.json` 的内容合并到 `.claude/settings.json` 的 `mcpServers` 字段，重启 Claude Code。

### 4. 在 Claude Code 中测试
- "帮我搜索进阶3天的川西徒步路线"
- "评估一下长穿毕路线的风险"
- "贡嘎大环线难度怎么样"

## 能力清单
| 类型 | 名称 | 说明 |
|------|------|------|
| Tool | search_routes_tool | 按难度/天数/区域搜索路线 |
| Tool | get_route_detail_tool | 获取路线详细信息 |
| Tool | assess_difficulty_tool | 评估路线难度等级 |
| Resource | route://database | 路线数据库 |
| Resource | route://safety-rules | 安全规则 |
| Prompt | route_assessment | 路线评估提示词模板 |
| Skill | route-assessment | 路线评估完整流程 |
```

---

## 运行与测试

### 1. 安装依赖

```bash
pip install mcp
```

### 2. 测试 MCP Client

```bash
cd e:/workspace/project/myAIAgentLearning/week08/day07
python client/mcp_client.py
```

预期输出：

```
============================================================
连接 hiking-route-server...
============================================================
握手完成，连接已建立

============================================================
发现工具 (tools/list)
============================================================
  - search_routes_tool: 搜索徒步路线。...
  - get_route_detail_tool: 获取指定路线的详细信息。...
  - assess_difficulty_tool: 评估路线难度等级。...

============================================================
发现资源 (resources/list)
============================================================
  - route://database: 路线数据库（只读资源）
  - route://safety-rules: 安全规则（只读资源）

============================================================
发现提示词 (prompts/list)
============================================================
  - route_assessment: 路线评估提示词模板...

============================================================
调用工具: search_routes_tool
============================================================
结果:
- 长穿毕（长坪沟穿越毕棚沟）（进阶/4天/川西）
- 雨崩徒步（进阶/5天/云南）

============================================================
调用工具: assess_difficulty_tool
============================================================
结果:
难度评估：进阶（得分 5/10）

评分明细：
- 海拔 4668m → +3 分
- 距离 45km → +2 分
- 天数 4天 → +0 分

参考标准：CMA 山地户外难度分级

============================================================
全部验证通过，能力包可接入 Claude Code
============================================================
```

### 3. 接入 Claude Code

```bash
# 把 config/claude_code_config.json 的内容合并到 .claude/settings.json
# 重启 Claude Code
# 输入 /mcp 查看连接状态
```

### 4. 在 Claude Code 中实测

| 输入 | 预期触发 |
|------|---------|
| 帮我搜索进阶3天的川西徒步路线 | 调用 search_routes_tool |
| 评估一下长穿毕路线的风险 | 触发 route-assessment Skill + 调三个工具 |
| 贡嘎大环线难度怎么样 | 调用 assess_difficulty_tool |
| 这条路线需要带什么装备 | 触发 Skill + 调 get_route_detail_tool |

### 验证要点

| 验证项 | 预期结果 |
|--------|---------|
| Client 能发现所有工具/资源/提示词 | 3 工具 + 2 资源 + 1 提示词 |
| 工具调用能跑通 | search/detail/assess 都返回正确结果 |
| Claude Code 能连上 Server | `/mcp` 显示 hiking-routes 连接正常 |
| 自然语言能触发工具 | 输入"搜索进阶路线"后 Claude 调用 search_routes_tool |
| 自然语言能触发 Skill | 输入"评估风险"后加载 SKILL.md 正文 |
| Skill 步骤被正确执行 | 按"搜→查→评→风险→装备→应急"顺序输出 |

### 执行流程示例

```
用户在 Claude Code 输入："评估一下长穿毕路线的风险"

Claude Code (Host) 处理：
  1. LLM 匹配 Skill description → "评估...风险" 命中 route-assessment
     → 触发 Skill，加载 SKILL.md 正文

  2. LLM 按 SKILL.md 步骤调工具：
     search_routes_tool("长穿毕")   → 确认路线存在
     get_route_detail_tool("长穿毕") → 海拔4668m/距离45km/风险/装备/救援点
     assess_difficulty_tool("长穿毕") → 进阶（得分5/10）

  3. LLM 按验收标准输出报告（5个维度）：
     难度评估 | 季节适宜性 | 风险点 | 装备建议 | 应急方案
```

---

## 动手实验

### 🟢 青铜：运行 MCP Client，验证工具发现

把 `client/mcp_client.py` 跑起来，确认：

1. Client 能成功连接 Server（不报连接错误）
2. 能发现 3 个工具 + 2 个资源 + 1 个提示词
3. 三个工具都能调用成功，返回正确结果
4. 资源能读取（`route://safety-rules` 返回安全规则文本）

**验收标准：** 看到"全部验证通过，能力包可接入 Claude Code"这行输出。

> **提示：** 如果报 `ModuleNotFoundError: No module named 'mcp_server'`，检查是不是在 `week08/day07` 目录下运行，以及 `mcp_server/__init__.py` 是否存在。

### 🟡 白银：接入 Claude Code，用自然语言实测

把 MCP Server 接入 Claude Code，用自然语言测试：

1. **工具触发测试：** 输入"帮我搜索进阶3天的川西徒步路线"，观察 Claude 是否调用 `search_routes_tool`
2. **Skill 触发测试：** 输入"评估一下长穿毕路线的风险"，观察是否触发 `route-assessment` Skill
3. **多工具编排测试：** 输入"对比长穿毕和雨崩徒步的难度"，观察 Claude 是否调用多次工具并综合对比

**验收标准：**
- `/mcp` 显示 hiking-routes 连接正常
- 自然语言能正确触发工具（不是 Claude 自己编答案）
- Skill 触发时输出包含全部 5 个评估维度

> **调试技巧：** 如果 Skill 不触发，先检查 SKILL.md 的 `description` 是否写清了"什么时候用"。Day 04 踩坑记录里讲过，description 写"路线评估"就不触发，写"对徒步路线进行全面风险评估，当用户要求评估风险时使用"才触发。

### 🔴 王者：给 MCP Server 加一个新工具 + smoke test

1. **加新工具：** 在 `mcp_server/tools.py` 加一个 `get_weather(region)` 工具，mock 天气数据
2. **注册到 Server：** 在 `server.py` 用 `@server.tool()` 注册
3. **写 smoke test：** 在 `client/` 下写一个 `test_smoke.py`，自动测试所有工具：
   - 调 `search_routes_tool` 验证返回非空
   - 调 `get_route_detail_tool("长穿毕")` 验证包含"4668"
   - 调 `assess_difficulty_tool("贡嘎大环线")` 验证返回"硬核"
   - 调 `get_weather("川西")` 验证返回天气信息
4. **更新 Skill：** 在 `SKILL.md` 的步骤里加入"调用 get_weather 获取天气"

**验收标准：**
- 新工具能被 Client 发现并调用
- smoke test 全部通过
- Skill 步骤里包含天气查询环节

```python
"""client/test_smoke.py — smoke test 模板"""
import asyncio
from mcp.client import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters


async def smoke_test():
    params = StdioServerParameters(
        command="python", args=["-m", "mcp_server.server"]
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 测试1：搜索路线返回非空
            r = await session.call_tool("search_routes_tool", {"difficulty": "进阶"})
            assert "长穿毕" in r.content[0].text, "搜索进阶路线应包含长穿毕"
            print("[PASS] search_routes_tool")

            # 测试2：详情包含海拔
            r = await session.call_tool("get_route_detail_tool", {"route_name": "长穿毕"})
            assert "4668" in r.content[0].text, "长穿毕海拔应为4668m"
            print("[PASS] get_route_detail_tool")

            # 测试3：贡嘎评估为硬核
            r = await session.call_tool("assess_difficulty_tool", {"route_name": "贡嘎"})
            assert "硬核" in r.content[0].text, "贡嘎应为硬核"
            print("[PASS] assess_difficulty_tool")

            print("\n全部 smoke test 通过")


asyncio.run(smoke_test())
```

---

## 踩坑记录 🕳️

### 坑 1：MCP Server 的 async 工具和 sync 调用混用导致死锁

Day 02 和 Day 06 都提过 async 的问题，今天在 `server.py` 里又踩了一次。`tools.py` 里的函数写成 `async def`，但 `assess_difficulty` 里不小心调了一个 sync 的阻塞函数（比如 `time.sleep`），结果整个 Server 卡死。

```python
# 错误：async 函数里调阻塞操作
async def assess_difficulty(route_name: str) -> str:
    import time
    time.sleep(2)  # 阻塞事件循环，整个 Server 卡死
    return "..."

# 正确：async 函数里用 await asyncio.sleep
async def assess_difficulty(route_name: str) -> str:
    await asyncio.sleep(2)  # 不阻塞事件循环
    return "..."
```

**解决：** MCP Server 跑在 asyncio 事件循环里，所有 IO 操作必须用 async 版本。`time.sleep` 用 `await asyncio.sleep` 替代，`requests.get` 用 `httpx.AsyncClient` 替代，`open()` 用 `aiofiles.open()` 替代。

### 坑 2：Claude Code 配置文件的路径要绝对路径或 cwd

Day 02 用相对路径 `args: ["mcp_server/server.py"]`，Claude Code 启动时的工作目录不一定是项目根目录，导致找不到文件。

```json
// 错误：相对路径，依赖当前工作目录
{
  "mcpServers": {
    "hiking-routes": {
      "command": "python",
      "args": ["mcp_server/server.py"]
    }
  }
}

// 正确：用 -m 模块方式 + cwd 指定工作目录
{
  "mcpServers": {
    "hiking-routes": {
      "command": "python",
      "args": ["-m", "mcp_server.server"],
      "cwd": "e:/workspace/project/myAIAgentLearning/week08/day07"
    }
  }
}
```

**解决：** 用 `-m mcp_server.server` 让 Python 按包路径查找，再用 `cwd` 锁定工作目录。这样无论 Claude Code 从哪里启动，都能正确找到 Server。

### 坑 3：Skill 的 description 写不好导致不触发

Day 04 重点讲过这个坑，今天又验证了一次。最初 `description` 写成"徒步路线评估"，结果输入"评估长穿毕的风险"根本不触发 Skill。

```yaml
# 错误：太短，Claude 不知道什么时候用
description: 徒步路线评估

# 正确：说清做什么 + 什么时候用
description: 对徒步路线进行全面风险评估，包含难度评级、季节适宜性、风险点、装备建议和应急方案。当用户要求评估某条徒步路线的风险、安全性、难度时使用此 Skill。
```

**解决：** description 要包含两个信息——"做什么"（全面风险评估）+"什么时候用"（当用户要求评估风险/安全性/难度时）。Day 04 的规则：description 越具体，触发率越高。

### 坑 4：MCP Server 崩溃后 Claude Code 不会自动重启

Day 06 提过 stdio 传输的局限——Server 子进程崩了，Client 连接直接断，Claude Code 不会自动重连。今天如果改了 `server.py`，必须重启 Claude Code 才能生效。

```
修改 server.py → 保存 → Claude Code 还在用旧的 Server 进程
                → 必须重启 Claude Code
                → 或者 /mcp 里手动重连（如果支持）
```

**解决：** 开发阶段用 `client/mcp_client.py` 调试，改完代码立刻 `python client/mcp_client.py` 验证，不用反复重启 Claude Code。验证通过后再接入 Claude Code 做端到端测试。

### 坑 5：工具名带 _tool 后缀导致 LLM 调用时多一层理解

最初为了和 `tools.py` 里的函数区分，Server 里注册的工具名都加了 `_tool` 后缀（`search_routes_tool`）。结果发现 LLM 调用时偶尔会混淆，因为它看到工具名是 `search_routes_tool`，但 SKILL.md 里写的是"调用 search_routes"。

```python
# 容易混淆的命名
@server.tool()
async def search_routes_tool(...):  # 工具名 search_routes_tool
    ...

# SKILL.md 里写："调用 search_routes"
# LLM 可能困惑：到底叫 search_routes 还是 search_routes_tool？
```

**解决：** 保持工具名和 SKILL.md 里的引用一致。要么 Server 里就叫 `search_routes`（和 tools.py 函数同名也行，因为有模块隔离），要么 SKILL.md 里写 `search_routes_tool`。两边对齐。

---

## 副线笔记

### 对比 Week 07 Day 07 的多 Agent 徒步规划系统

这是本周最重要的对比。同样是"徒步路线评估"场景，Week 07 和 Week 08 用了完全不同的技术路线：

| 维度 | Week 07 Day 07（多 Agent） | Week 08 Day 07（MCP + Skill） |
|------|---------------------------|-------------------------------|
| 架构 | LangGraph create_agent + Subagents | MCP Server + SKILL.md + Client |
| 工具形态 | `@tool` Python 函数（同进程） | MCP Server 暴露的远程能力（跨进程） |
| 流程编排 | 主 Agent 的 system_prompt 里写流程 | 独立的 SKILL.md 文件 |
| 知识复用 | 写死在某个 Agent 里 | Skill 独立存在，任何 Host 都能加载 |
| 客户端 | LangGraph runtime | 任何 MCP Client（Claude Code / Cursor） |
| 部署 | 一个 FastAPI 服务 | Server + Skill + Client 三个独立组件 |
| 扩展性 | 加工具要改 Agent 代码 | 加 Server 配置，Agent 代码不动 |
| 跨语言 | 不能（Python only） | 能（JSON Schema 通用） |

核心差异用一句话说清：

```
Week 07：能力 = 框架内函数（紧耦合，只能在 LangGraph 项目里用）
Week 08：能力 = 标准化服务 + 可复用流程（松耦合，跨平台可用）
```

### 两种方式的取舍

| 场景 | 推荐 | 原因 |
|------|------|------|
| 单一框架内的复杂多 Agent 协作 | Week 07 方式 | 上下文隔离、并行能力强，框架提供完整支持 |
| 工具需要被多个 Host 复用 | Week 08 方式 | MCP 标准化，一次开发到处可用 |
| 团队多语言技术栈 | Week 08 方式 | JSON Schema 跨语言 |
| 快速验证想法 | Week 07 方式 | `@tool` 上手快，不用搭 Server |
| 生产环境长期维护 | Week 08 方式 | Server 和 Skill 独立版本化，便于迭代 |

> **实战建议：** 不是非此即彼。Week 07 的多 Agent 系统里，子 Agent 可以调用 MCP Server 的工具——LangGraph 的 `@tool` 可以包装一个 MCP Client 调用。Week 07 管编排，Week 08 管能力，两者结合是最完整的方案。

### Skill 的 description 是"触发器"不是"说明书"

今天又验证了 Day 04 的核心认知：Skill 的 `description` 决定它会不会被触发，不是决定它怎么执行。Claude 启动时只读 frontmatter 的 `description`（几十 token）做语义匹配，触发后才加载正文（几百 token）按步骤执行。这就像简历的"求职意向"——HR 扫一眼决定约不约面试（触发），面试时才看详细经历（正文）。description 写不好，连面试机会都没有。

### 全程 Claude Code 结对编程的体会

和 Week 07 一样的流程：你画架构图 → 定义工具签名和验收标准 → Claude Code 出代码骨架 → 你审查改 description 和参数命名 → 跑 client 验证 → Claude Code 辅助调试。关键原则不变：**架构决策权在你手里**——"该不该把流程写在 Server 里""description 怎么写""工具名加不加后缀"这些决策必须你来定。

### 今日观察任务

- 打开 Claude Code 的 `/mcp` 面板，观察 hiking-routes 连接状态
- 输入"评估长穿毕路线的风险"，观察 Claude 是先触发 Skill 还是直接调工具
- 对比 Claude Code 调 MCP 工具和 Week 07 调 `@tool` 的体验差异
- 思考：把 Week 07 多 Agent 系统迁移到 MCP 架构，哪些部分变 Server，哪些变 Skill？

---

## 检查清单

- [ ] MCP Server 能正常启动（`python -m mcp_server.server` 不报错）
- [ ] Client 能发现所有工具/资源/提示词（3+2+1）
- [ ] 三个工具都能调用成功并返回正确结果
- [ ] 资源能读取（route://database / route://safety-rules）
- [ ] SKILL.md 结构完整（frontmatter + 步骤 + 验收标准 + 约束）
- [ ] SKILL.md 的 description 写清了"做什么 + 什么时候用"
- [ ] Skill 的辅助文件（checklist.md / grade.py）存在且被引用
- [ ] 成功接入 Claude Code（`/mcp` 显示连接正常）
- [ ] Claude Code 能用自然语言调用工具
- [ ] Claude Code 能触发 route-assessment Skill
- [ ] Skill 触发后输出包含全部 5 个评估维度
- [ ] grade.py 能独立运行（`python grade.py --name "长穿毕"`）

---

## 本周总结

回顾 Week 08 的学习路径：

| Day | 主题 | 核心收获 |
|-----|------|---------|
| Day 01 | MCP 核心概念 | MCP 把 `@tool` 从"同进程函数"升级成"跨进程标准协议" |
| Day 02 | MCP Server 开发 | Tool / Resource / Prompt 三种能力 + 接入 Claude Code |
| Day 03 | Skills 概念 | Skill 是"能力包"不是"提示词"，可发现、可版本化、可分发 |
| Day 04 | SKILL.md 实战 | frontmatter 是名片，正文是操作手册，description 决定触发 |
| Day 05 | A2A / ACP 协议 | Agent 间通信的标准化，对比 Handoffs 的框架内流转 |
| Day 06 | MCP 客户端 | Client 五阶段生命周期 + 动态发现 vs 静态注册 |
| Day 07 | 综合产出 | MCP Server + Skill + Client 组装成完整能力包 |

### 本周核心升级路径

```
Week 06：单 Agent（create_agent + @tool）
  → 工具是同进程 Python 函数，流程写在 system_prompt 里，只能在这个项目里用

Week 07：多 Agent（Subagents 模式）
  → 主 Agent 协调子 Agent，上下文隔离，但工具仍是 @tool，还是框架内的事

Week 08：协议生态（MCP + Skills + A2A）
  → 工具变成 MCP Server（跨进程、跨语言、可复用）
  → 流程变成 SKILL.md（独立文件、按需加载、任何 Host 都能用）
  → 核心升级：标准化——MCP 让工具跨进程，A2A 让 Agent 跨框架，Skills 让能力可复用
```

### Skill vs Tool vs MCP vs Prompt（本周终极对比）

| 概念 | 本质 | 生命周期 | 本周对应 |
|------|------|---------|---------|
| Tool | 可调用的函数接口 | 单次调用 | search_routes_tool 等 |
| Prompt | 一次性指令 | 单次使用 | route_assessment 提示词模板 |
| MCP | 标准化工具协议 | 跨进程持续 | hiking-route-server |
| Skill | 可复用的能力包 | 可发现、可版本化 | route-assessment（SKILL.md + 附件） |

### 项目代码行数（填）：________

### 最大的收获：
________________________________

### 踩过最大的坑 & 怎么解决的：
________________________________

### 还没搞懂的（诚实写）：
________________________________

### 用 Claude Code 结对编程的体验：
________________________________

---

## 下周预告

Week 09 进入 Agent 评测 + 可观测性 + 安全——让 Agent 从"能跑"到"能评、能观测、能防御"。

本周搭的能力包"好不好"全靠手动测试——输几句话看看对不对。真实生产环境这远远不够：

- **评测：** 怎么量化 Agent 表现？准确率、延迟、token 消耗、边界 case 覆盖率？Week 04 的 RAG 评测方法论会升级到 Agent 评测
- **可观测性：** Agent 跑的时候内部发生了什么？调了哪个工具、卡在哪一步、为什么选错？需要 trace / metrics / logs
- **安全：** prompt injection、工具滥用、数据泄露、权限控制——Agent 能调用工具就有风险

```
Week 08：能跑（能力包搭建完成）
Week 09：能评（评测）+ 能观测（trace）+ 能防御（安全）
```

> **认知升级预告：** Week 06-08 你学会了"搭 Agent"——从单 Agent到多 Agent 到协议生态。Week 09 开始学"管 Agent"——评测、监控、安全。前者是"造"，后者是"治"，两者都到位才算真正掌握 Agent 工程。
