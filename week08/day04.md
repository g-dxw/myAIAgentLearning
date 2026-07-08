# Day 04 — SKILL.md 实战：写一个可复用能力包

## 学习目标

Day 03 我们搞清楚了 Skills 是什么——一个可发现、可版本化、可分发的"能力包"，不是一段提示词。我们还学了按需加载机制：启动时只读 `name` + `description`（几十 token），调用时才加载完整内容。那是"道"，今天是"术"。

今天不讲概念了，直接上手写。你会从零创建一个完整的 SKILL.md，挂上辅助脚本和模板文件，再写 smoke test 验证效果。写完之后你对 Skill 的理解会从"知道是什么"升级成"知道怎么写、怎么用、怎么验证"——这才是真会了。

学完今天你能：

1. 能写一个完整的 SKILL.md，包含 frontmatter、步骤、验收标准
2. 理解 SKILL.md 的文件结构：YAML frontmatter + Markdown 正文 + 辅助文件
3. 能给 Skill 加辅助脚本和模板文件
4. 知道什么时候才需要加载 Skill，以及如何写 smoke test 验证 Skill 效果

---

## 一、SKILL.md 完整结构详解

### 1.1 SKILL.md 的两部分：frontmatter + 正文

Day 03 我们看过 SKILL.md 的"外貌"，今天拆开来一个字段一个字段讲。

SKILL.md = YAML frontmatter（元数据）+ Markdown 正文（流程指令）。frontmatter 告诉 Claude "这个 Skill 叫什么、干嘛的"，正文告诉 Claude "具体怎么做"。

```
SKILL.md 结构
┌─────────────────────────────────┐
│  YAML frontmatter（元数据）       │  ← Claude 启动时就读这部分
│  ---                             │
│  name: code-review               │
│  description: 一句话描述          │
│  ---                             │
│                                  │
│  Markdown 正文（流程指令）         │  ← 调用时才加载这部分
│  # 标题                          │
│  ## 何时使用                      │
│  ## 步骤                         │
│  ## 验收标准                      │
│  ## 约束                         │
└─────────────────────────────────┘
```

记住 Day 03 的核心：frontmatter 是"名片"（几十 token），正文是"操作手册"（几百上千 token）。名片随时带身上，操作手册用的时候才翻开。

### 1.2 frontmatter 字段详解

frontmatter 目前只有两个核心字段，但这两个字段的写法决定了 Skill 的"生死"——写得好，Agent 能正确发现和调用；写得烂，Skill 就是个摆设。

**name：Skill 的唯一标识**

```yaml
name: code-review
```

规则：
- 必须用 kebab-case（小写字母 + 短横线），不要用驼峰或下划线
- 名字就是斜杠命令的名字：`/code-review` 靠的就是这个字段
- 要语义清晰：看到名字就知道这个 Skill 干什么
- 好的名字：`code-review`、`deploy-check`、`pr-template`
- 坏的名字：`cr`（太短看不懂）、`codeReview`（不是 kebab-case）、`my-skill-1`（太笼统）

**description：一句话描述**

```yaml
description: 对代码进行全面审查，检查安全、性能、可维护性，输出审查报告
```

这个字段极其关键——Claude 启动时只读这一个字段来判断"什么时候该调用这个 Skill"。描述写得模糊，Agent 就不知道什么时候该用它；描述写得太宽泛，Agent 会在不该调用的时候误触发。

好的 description 要满足两个条件：

1. **说清楚"做什么"**：这个 Skill 执行什么任务
2. **暗示"什么时候用"**：什么场景下该触发

对比一下：

| description | 评价 | 原因 |
|------------|------|------|
| `代码审查` | 差 | 太短，Agent 不知道审查什么、输出什么 |
| `对代码进行审查和分析` | 一般 | "分析"太模糊，什么算分析？ |
| `对代码进行全面审查，检查安全、性能、可维护性，输出审查报告` | 好 | 说清了做什么（审查三类问题）和输出什么（审查报告） |

### 1.3 正文结构：步骤 + 验收标准 + 约束

正文是 Skill 的"灵魂"，写的是"怎么完成这类任务"。推荐包含四个部分：

```
正文结构
├── 何时使用     ← 什么场景下触发这个 Skill
├── 步骤         ← 按步骤执行的流程（核心！）
├── 验收标准     ← 完成条件，怎么判断"做完了"
└── 约束         ← 限制条件，"不能做什么"
```

为什么要写"何时使用"和"约束"？因为 Skill 加载后，Claude 要知道边界——哪些事该做，哪些事不该做。没有边界，Claude 可能跑偏。

### 1.4 完整示例：code-review Skill

下面是一个完整的 code-review SKILL.md，每个部分都加了注释说明：

```markdown
---
name: code-review
description: 对代码进行全面审查，检查安全、性能、可维护性，输出审查报告
---

# 代码审查流程

## 何时使用
- 用户请求审查代码时
- PR 提交前的自动检查
- 代码合并前的质量把关

## 步骤

### 1. 读取目标代码
- 确定审查范围（文件/目录/PR diff）
- 读取相关代码文件

### 2. 安全检查
- SQL 注入风险
- XSS 漏洞
- 硬编码密钥/密码
- 不安全的反序列化

### 3. 性能检查
- N+1 查询
- 不必要的循环嵌套
- 内存泄漏风险
- 未释放的资源

### 4. 可维护性检查
- 命名规范
- 函数复杂度
- 注释完整性
- 重复代码

## 验收标准
- [ ] 输出审查报告（Markdown 格式）
- [ ] 每个问题标注严重程度（高/中/低）
- [ ] 给出修复建议和代码示例
- [ ] 统计问题数量

## 约束
- 只审查指定范围的代码
- 不修改代码，只提建议
- 严重问题必须标红
```

逐部分拆解：

**何时使用**——给了三个触发场景。这样 Claude 看到"帮我审查代码"、"PR 检查"这类请求时，就知道该调用这个 Skill。

**步骤**——4 个步骤，每步有具体检查项。注意步骤是"有序的"：先读代码，再安全检查，再性能检查，最后可维护性。Claude 会按这个顺序执行。

**验收标准**——用 checkbox 格式，4 条标准。Claude 完成后会对照这些标准自查："我有没有输出报告？有没有标严重程度？有没有给修复建议？有没有统计问题数？"缺一项就说明没做完。

**约束**——3 条限制。关键的是"不修改代码，只提建议"——没有这条约束，Claude 可能会直接帮你改代码，那就不是"审查"而是"修复"了。

> **前端类比：** 验收标准就像 Vue 组件的 `emits` 声明——它定义了这个 Skill 的"输出接口"。调用方（Claude 或用户）看到验收标准就知道"这个 Skill 会给我什么"。约束就像 `props` 的 `validator`——定义了输入的边界。

---

## 二、给 Skill 加辅助文件

### 2.1 Skill 不只是 SKILL.md

Day 03 我们说过，Skill 是一个"工具箱"，SKILL.md 是"操作说明"，辅助文件是"扳手和螺丝刀"。光有操作说明的 Skill 能用，但加上辅助文件后，效果会好很多——因为 Agent 可以引用更精确的模板和脚本。

一个完整的 Skill 文件结构：

```
.claude/skills/
└── code-review/
    ├── SKILL.md          # 核心定义（必须有）
    ├── checklist.md      # 审查清单模板（可选）
    ├── severity.md       # 严重程度定义（可选）
    └── analyze.py        # 辅助分析脚本（可选）
```

辅助文件怎么和 SKILL.md 关联？在 SKILL.md 正文里引用它们。Claude 加载 Skill 时，会顺着引用去读取这些文件。

在步骤里加引用的方式：

```markdown
### 2. 安全检查
- 参照 checklist.md 中的安全清单逐项检查
- 使用 severity.md 中的标准标注严重程度
```

这样 Claude 读到这一步时，就知道要去读 `checklist.md` 和 `severity.md`。

### 2.2 checklist.md：审查清单模板

清单模板的作用是让检查"不遗漏"。没有清单，Claude 可能凭感觉查，查到什么算什么；有了清单，Claude 会逐项核对，像质检员一样一项一项打勾。

```markdown
# 代码审查清单

## 安全
- [ ] 所有用户输入都经过校验
- [ ] 没有硬编码的密钥
- [ ] SQL 查询使用参数化
- [ ] 文件上传有大小限制
- [ ] 敏感数据有加密传输

## 性能
- [ ] 没有N+1查询
- [ ] 循环内没有不必要的IO
- [ ] 大列表做了分页
- [ ] 没有同步阻塞调用
- [ ] 缓存策略合理

## 可维护性
- [ ] 函数不超过50行
- [ ] 嵌套不超过3层
- [ ] 变量命名语义清晰
- [ ] 公共API有注释
- [ ] 没有重复代码（DRY原则）
```

为什么要把清单从 SKILL.md 正文里拆出来？两个原因：

1. **职责分离**：SKILL.md 写"流程"（先做什么后做什么），checklist.md 写"检查项"（每步要查什么）。流程是稳定的，检查项可能经常调整——拆开可以独立修改。
2. **token 节省**：如果用户只是问"这个 Skill 能干什么"，Claude 只需要读 SKILL.md；只有在实际执行审查时，才需要读 checklist.md。

### 2.3 severity.md：严重程度定义

这个文件定义"什么算高、什么算中、什么算低"。没有统一定义，Claude 可能把 SQL 注入标成"低"——那审查报告就没法看了。

```markdown
# 问题严重程度定义

## 高（P0）— 必须立即修复
- 安全漏洞（SQL注入、XSS、硬编码密钥）
- 数据丢失风险
- 服务崩溃风险

## 中（P1）— 本迭代内修复
- 性能瓶颈（N+1查询、内存泄漏）
- 可维护性差（复杂度过高、重复代码）
- 缺少错误处理

## 低（P2）— 有空再修
- 命名不规范
- 注释缺失
- 代码风格不一致
```

### 2.4 analyze.py：辅助分析脚本

辅助脚本是 Skill 里的"计算工具"——当 Claude 需要做一些精确计算时，可以参考脚本里的逻辑。

```python
"""analyze.py — 代码审查辅助脚本

不是给 Agent 直接调用的工具，而是 Skill 加载时可以引用的辅助文件。
Agent 读到这个文件后，可以理解如何分析代码复杂度。
"""
import ast

def calculate_complexity(source: str) -> dict:
    """计算代码复杂度"""
    tree = ast.parse(source)
    # 简化版复杂度计算
    functions = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    return {
        "function_count": len(functions),
        "max_depth": max((n.body for n in functions), default=0, key=len),
    }

def find_long_functions(source: str, threshold: int = 50) -> list:
    """找出超长函数"""
    tree = ast.parse(source)
    long_funcs = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            # 统计函数体行数（简化版）
            end_line = getattr(node, "end_lineno", node.lineno)
            length = end_line - node.lineno + 1
            if length > threshold:
                long_funcs.append({
                    "name": node.name,
                    "line": node.lineno,
                    "length": length,
                })
    return long_funcs
```

注意这段脚本的关键注释：**"不是给 Agent 直接调用的工具"**。辅助脚本是"参考文件"，不是"可执行工具"。Agent 读取它后理解了复杂度计算的逻辑，就能在审查时用同样的思路去分析代码——但不是真的 `python analyze.py` 跑一下。

### 2.5 辅助文件的加载时机

辅助文件不会在 Skill 被触发时全部加载——只有 SKILL.md 正文里引用到的文件才会被读取。这又是 Day 03 说的"按需加载"。

```
Skill 加载流程：
1. 触发 code-review Skill
2. 加载 SKILL.md 正文
3. 读到"参照 checklist.md" → 加载 checklist.md
4. 读到"使用 severity.md" → 加载 severity.md
5. 读到"参考 analyze.py" → 加载 analyze.py
6. 按照完整内容执行审查
```

这意味着：如果你在 SKILL.md 里不引用某个辅助文件，它就不会被加载。所以**辅助文件一定要在 SKILL.md 步骤里显式引用**，否则等于白放。

### 2.6 辅助文件的数量控制

Day 03 我们说过，Skill 有 token 预算。辅助文件太多，加载后会撑爆预算。实战建议：

| 辅助文件数 | 效果 | 建议 |
|-----------|------|------|
| 0-2 个 | 轻量，加载快 | 简单 Skill 够用 |
| 3-5 个 | 适中，覆盖全面 | 推荐，大多数 Skill 这个量 |
| 6+ 个 | 可能超预算 | 考虑拆成多个 Skill |

如果你的 Skill 需要很多辅助文件，说明这个 Skill 可能做得太多了——拆成多个小 Skill 比一个大 Skill 更好管理。

> **户外类比：** 写 Skill 就像整理登山包。你不会把所有装备都塞主舱——那样找东西太慢。你会分仓：主舱放必需品（SKILL.md），侧袋放常用工具（checklist），顶包放应急物品（脚本）。每个仓都有明确用途，取用高效。辅助文件太多就像主舱塞爆了，背着累，找东西也慢。

---

## 三、Skill 的触发机制和 Smoke Test

### 3.1 两种触发方式

Skill 有两种触发方式，对应两种使用场景：

**方式一：手动触发——斜杠命令**

```
用户输入：/code-review
```

这是最直接的方式。用户明确知道要用这个 Skill，输入斜杠命令，Claude 直接加载并执行。适合"我知道我要做什么"的场景。

**方式二：自动触发——Claude 根据 description 匹配**

```
用户说："帮我审查一下 auth.py 有没有安全问题"
Claude 判断：这是一个代码审查任务 → 自动触发 code-review Skill
```

这是更"智能"的方式。Claude 启动时已经知道有哪些 Skill（读过 frontmatter），当用户的请求和某个 Skill 的 description 匹配时，自动触发。

两种方式的触发链路对比：

```
手动触发：                        自动触发：
用户输入 /code-review            用户说"审查auth.py"
    │                                │
    ▼                                ▼
Claude 匹配到 Skill name          Claude 匹配到 Skill description
    │                                │
    ▼                                ▼
加载 SKILL.md 完整内容             加载 SKILL.md 完整内容
    │                                │
    ▼                                ▼
按步骤执行                         按步骤执行
```

### 3.2 description 决定自动触发的成功率

自动触发的关键在 description。写得好，Claude 能准确匹配；写得烂，Skill 就是"存在但没人用"的僵尸。

三招写好 description：

**第一招：包含动词**

```yaml
# 差
description: 代码审查工具

# 好
description: 对代码进行全面审查，输出审查报告
```

"代码审查工具"是名词，Agent 不知道它"做什么"。"对代码进行全面审查"是动词短语，Agent 一看就知道"这个 Skill 会执行审查动作"。

**第二招：说清输出物**

```yaml
# 差
description: 审查代码的安全和性能

# 好
description: 对代码进行全面审查，检查安全、性能、可维护性，输出审查报告
```

"输出审查报告"让 Agent 知道用完这个 Skill 会得到什么——当用户问"帮我查一下代码问题"时，Agent 就会想"用户需要一份审查报告，正好有这个 Skill"。

**第三招：包含触发场景关键词**

```yaml
# 差
description: 审查代码质量

# 好
description: 对代码进行全面审查，适用于PR检查、合并前质量把关、代码安全审计
```

"PR检查"、"合并前"、"安全审计"是用户常用的说法。当用户说"帮我查一下这个 PR"时，Agent 能匹配到"PR检查"这个关键词。

### 3.3 什么时候才需要加载 Skill？

不是所有任务都需要 Skill。回忆 Day 03 的选型规则：

```
用户的问题是什么类型？
│
├─ 事实类："这个项目怎么启动？" → CLAUDE.md 够了
│
├─ 简单动作："读一下这个文件" → 不需要 Skill，Tool 够了
│
└─ 流程类："帮我审查代码" → 需要 Skill
    │
    ├─ 步骤少（1-2步） → 直接告诉 Claude 怎么做就行
    └─ 步骤多（3步以上） → 写成 Skill，按步骤执行
```

Skill 的价值在于"步骤多、容易遗漏"的任务。如果只有一两步，直接在对话里告诉 Claude 就行，没必要创建 Skill。但如果是"代码审查"这种有 4 个步骤、每步有多个检查项的任务，Skill 的价值就体现出来了——确保每一步都执行到位，不遗漏。

### 3.4 写 Smoke Test 验证 Skill 效果

Skill 写好了，怎么验证它真的有用？靠人肉测试太主观，我们需要一个系统化的方法：**Smoke Test**。

Smoke Test 的思路很简单：准备几个测试任务，对比"有 Skill"和"无 Skill"的执行效果。如果加了 Skill 后效果明显提升，说明 Skill 写得有用；如果差不多，说明 Skill 要么写得不好，要么这个任务根本不需要 Skill。

```python
"""skill_smoke_test.py — Skill 效果验证脚本"""
import json

# 测试用例：每个包含输入和期望输出
test_cases = [
    {
        "input": "审查 main.py 的安全性",
        "expected": "包含安全检查报告",
    },
    {
        "input": "检查 api/ 目录的代码质量",
        "expected": "包含性能和可维护性分析",
    },
    {
        "input": "PR #42 的代码审查",
        "expected": "包含严重程度标注和修复建议",
    },
]

def run_comparison(test_cases):
    """对比：无 Skill vs 有 Skill"""
    results = []

    for case in test_cases:
        # 无 Skill：直接让 Claude 审查
        result_without = agent.invoke(case["input"])

        # 有 Skill：加载 code-review Skill 后审查
        result_with = agent_with_skill.invoke(case["input"])

        # 评估维度
        evaluation = {
            "input": case["input"],
            "expected": case["expected"],
            "without_skill": {
                "response": result_without,
                "structured": check_structured(result_without),    # 是否结构化
                "severity_labeled": check_severity(result_without), # 是否标注严重程度
                "fix_suggestions": check_fixes(result_without),     # 是否有修复建议
            },
            "with_skill": {
                "response": result_with,
                "structured": check_structured(result_with),
                "severity_labeled": check_severity(result_with),
                "fix_suggestions": check_fixes(result_with),
            },
        }
        results.append(evaluation)

    return results

def check_structured(response: str) -> bool:
    """检查输出是否结构化（有标题、列表等）"""
    return "##" in response or "- " in response

def check_severity(response: str) -> bool:
    """检查是否标注了严重程度"""
    keywords = ["高", "中", "低", "P0", "P1", "P2", "严重", "警告"]
    return any(kw in response for kw in keywords)

def check_fixes(response: str) -> bool:
    """检查是否给出了修复建议"""
    keywords = ["建议", "修复", "改为", "替换", "优化"]
    return any(kw in response for kw in keywords)
```

这个 smoke test 的核心逻辑：

1. **3-5 个测试用例**：覆盖 Skill 的主要使用场景
2. **对比有/无 Skill**：同一个任务跑两遍
3. **量化评估**：不是"感觉好一点"，而是检查具体维度——是否结构化、是否标注严重程度、是否给修复建议

### 3.5 解读 Smoke Test 结果

跑完 smoke test 后，对比结果可能长这样：

| 测试用例 | 维度 | 无 Skill | 有 Skill |
|---------|------|---------|---------|
| 审查 main.py | 结构化 | 散段落 | 有标题分段 |
| 审查 main.py | 严重程度 | 部分标注 | 全部标注 |
| 审查 main.py | 修复建议 | 偶尔给 | 每个问题都给 |
| 检查 api/ | 性能分析 | 提到1项 | 按清单逐项检查 |
| PR #42 | 完整度 | 60% | 95% |

关键看两个指标：

1. **完整性**：有 Skill 的结果是否更全面、不遗漏检查项
2. **一致性**：有 Skill 的结果是否每次都差不多（格式统一、不漏项）

如果 smoke test 显示"有 Skill 和无 Skill 差不多"，那有两种可能：

- Skill 写得不好（步骤太粗、检查项太少）
- 这个任务本身就不需要 Skill（太简单，直接做就行）

不管是哪种，都说明需要调整——要么改 Skill，要么放弃 Skill 改用其他方式。

---

## 动手实验

### 🟢 青铜：创建最小 code-review Skill

在 `.claude/skills/code-review/` 下创建 SKILL.md，只写 frontmatter + 基本步骤。

```markdown
---
name: code-review
description: 对代码进行全面审查，检查安全、性能、可维护性
---

# 代码审查流程

## 步骤
1. 读取目标代码
2. 安全检查（SQL注入、XSS、硬编码密钥）
3. 性能检查（N+1查询、不必要的循环）
4. 可维护性检查（命名、注释、复杂度）

## 验收标准
- 输出审查报告
- 标注严重程度
- 给出修复建议
```

做完后在 Claude Code 里输入 `/`，看是否出现 `/code-review`。

### 🟡 白银：完成 code-review 完整能力包

在青铜基础上，补全 `checklist.md` + `severity.md` + `analyze.py`，并在 SKILL.md 的步骤里引用这些辅助文件。

最终文件结构：

```
.claude/skills/
└── code-review/
    ├── SKILL.md          ← 在步骤里引用 checklist.md、severity.md、analyze.py
    ├── checklist.md      ← 审查清单（安全5项 + 性能5项 + 可维护性5项）
    ├── severity.md       ← 严重程度定义（高/中/低各自的标准）
    └── analyze.py        ← 复杂度计算 + 超长函数检测
```

在 SKILL.md 里这样引用：

```markdown
### 2. 安全检查
- 参照 checklist.md 中的安全清单逐项检查
- 使用 severity.md 中的标准标注严重程度

### 3. 性能检查
- 参照 checklist.md 中的性能清单逐项检查

### 4. 可维护性检查
- 参照 checklist.md 中的可维护性清单逐项检查
- 参考 analyze.py 的逻辑分析函数复杂度
```

### 🔴 王者：写 Smoke Test 验证 Skill 效果

写一个 `skill_smoke_test.py`，对比"有 Skill"和"无 Skill"的审查质量：

1. 准备 3-5 个测试任务（审查单个文件、审查目录、审查 PR diff）
2. 每个任务跑两遍：无 Skill 直接审 + 有 Skill 按流程审
3. 评估维度：结构化程度、严重程度标注、修复建议完整度、检查项覆盖率
4. 输出对比表格，结论写清楚 Skill 是否真的提升了质量

把 smoke test 脚本放到 `e:\workspace\project\myAIAgentLearning\week08\day04\skill_smoke_test.py`。

> **提示：** 如果没有真实的 Claude Code 环境跑对比，可以手动模拟——先不带 Skill 跑一次记录结果，再带上 Skill 跑一次，然后对比两次输出的质量差异。重点是体验"有流程指导"和"凭感觉做"的差别。

---

## 踩坑记录 🕳️

### 坑 1：description 写得不好导致 Agent 不会自动触发 Skill

最常见的坑。你辛辛苦苦写了一个 Skill，结果 Claude 从来不自动调用它——因为 description 写得太模糊。

```yaml
# 这些 description 都不会触发自动调用
description: 代码审查        # 太短，Agent 不知道审查什么
description: 工具            # 完全不知道干嘛的
description: 帮助开发者      # 太宽泛，什么都能匹配等于什么都匹配不上
```

**解决：** 按"动词 + 做什么 + 输出什么"的公式写 description。比如"对代码进行全面审查（做什么），检查安全、性能、可维护性（具体内容），输出审查报告（输出物）"。

### 坑 2：SKILL.md 太长会占用过多 token

有人觉得"正文写得越详细越好"，把 SKILL.md 写到 500 行。结果加载一个 Skill 就吃掉几千 token，一次对话用两个 Skill 上下文就快满了。

**解决：** SKILL.md 正文控制在 100-200 行以内。太细的检查项放到 checklist.md 里，太复杂的分析逻辑放到辅助脚本里。SKILL.md 只写"流程骨架"，辅助文件写"细节血肉"。

```
SKILL.md 正文长度建议：

  太短（<30行）  → 步骤太粗，Agent 不知道怎么做
  适中（50-200行）→ 流程清晰，辅助文件补细节  ← 推荐
  太长（>300行）  → token 爆炸，加载后撑上下文
```

### 坑 3：辅助文件太多超过 token 预算

有人给 code-review Skill 加了 8 个辅助文件：checklist.md、severity.md、analyze.py、style-guide.md、naming-convention.md、architecture.md、api-rules.md、test-template.md。加载时 Claude 要把 SKILL.md + 8 个文件全读进上下文，直接超预算。

**解决：** 一个 Skill 的辅助文件控制在 3-5 个以内。如果有更多内容需要引用，拆成多个 Skill。比如 `code-review-style` 专门管代码风格，`code-review-security` 专门管安全问题。

### 坑 4：Skill 和 CLAUDE.md 的内容不要重复

有人把"这个项目用 TypeScript"、"后端是 FastAPI"写进了 SKILL.md 正文。这些是事实信息，应该放 CLAUDE.md（Day 03 说过的选型规则）。SKILL.md 里只写"流程步骤"。

**问题：** 重复内容的危害不只是"多占 token"——如果 CLAUDE.md 和 SKILL.md 对同一个事实的描述不一致（比如一个说"用 pnpm"一个说"用 npm"），Agent 会困惑，不知道该信谁。

**解决：** 事实信息放 CLAUDE.md，流程步骤放 SKILL.md。两者各管各的，不重叠。

```
CLAUDE.md（事实）：           SKILL.md（流程）：
"项目用 pnpm"                "1. 读取目标代码"
"后端 FastAPI 8000端口"       "2. 安全检查"
"目录结构 src/..."            "3. 性能检查"
                              "4. 验收标准"
```

---

## 副线笔记

### 写一个 route-assessment Skill：徒步路线风险评估

结合 CMA 山地户外教练的背景，来写一个实际可用的 Skill——徒步路线风险评估流程。这个 Skill 可以在每次带队出发前，用 Claude Code 调用来系统化评估路线风险。

文件结构：

```
.claude/skills/
└── route-assessment/
    ├── SKILL.md           # 核心流程
    ├── risk-checklist.md  # 风险清单
    └── emergency.md       # 应急方案模板
```

SKILL.md：

```markdown
---
name: route-assessment
description: 评估徒步路线的安全风险，分析海拔、天气、装备、体能因素，输出风险评估报告和应急方案
---

# 徒步路线风险评估流程

## 何时使用
- 出发前的路线安全评估
- 新路线的踩点分析
- 天气变化后的路线重评估
- 多日线补给的可行性判断

## 步骤

### 1. 海拔评估
- 起点海拔与终点海拔差
- 累计爬升与累计下降
- 是否超过3500米（高反风险）
- 是否有陡峭暴露路段

### 2. 天气风险评估
- 近3天天气预报（降水、风力、温差）
- 是否有雷暴/大风预警
- 气温随海拔变化的梯度
- 溪流水位与降雨关系

### 3. 装备与补给检查
- 参照 risk-checklist.md 逐项核对
- 队伍人数与公共装备配比
- 饮水量与补给点分布
- 通讯信号覆盖情况

### 4. 应急方案
- 参照 emergency.md 生成应急方案
- 撤退路线标注
- 最近医疗点距离
- 紧急联络人列表

## 验收标准
- [ ] 输出风险评估报告（Markdown格式）
- [ ] 每个风险标注等级（高/中/低）
- [ ] 给出"是否建议出行"的明确结论
- [ ] 附带应急方案

## 约束
- 只评估风险，不替用户做决策
- 天气数据需注明来源和时效
- 高海拔（>3500m）必须标注高反风险
```

risk-checklist.md：

```markdown
# 徒步风险检查清单

## 装备
- [ ] 登山鞋（防滑性能达标）
- [ ] 登山杖（双人双杖或单杖）
- [ ] 头灯及备用电池
- [ ] 保暖层（中层+外层）
- [ ] 雨具（冲锋衣或雨披）
- [ ] 急救包（含止血带、绷带、药品）
- [ ] 哨子

## 补给
- [ ] 每人每日至少2L饮水
- [ ] 高热量食物储备（+20%冗余）
- [ ] 电解质补充
- [ ] 补给点之间的最长无补给距离

## 通讯
- [ ] 手机信号覆盖区域标注
- [ ] 无信号区域的卫星通讯方案
- [ ] 领队及收队的联络方式
- [ ] 紧急撤离联络人
```

emergency.md：

```markdown
# 应急方案模板

## 通用应急流程
1. 停止前进，评估伤情/险情
2. 确保自身安全（不要造成二次伤害）
3. 现场急救（止血/固定/保暖）
4. 评估是否需要紧急撤离
5. 联络外部救援

## 撤退路线
- 主路线：[根据实际路线填写]
- 备用路线：[根据实际路线填写]
- 撤退所需时间：[估算]

## 紧急联络
- 当地救援电话：119 / 110
- 最近医院：[根据路线填写]
- 队伍紧急联络人：[领队电话]
```

这个 Skill 的实用价值在于：每次带队出发前，输入路线信息，Claude 就会按 4 个步骤系统化评估风险、核对装备、生成应急方案。比"凭经验想想"靠谱得多——尤其在新路线或天气不确定的时候。

> **教练视角：** CMA 教练体系里有一句话叫"安全是底线，不是上限"。route-assessment Skill 做的就是把"底线"系统化——不是每次都靠教练经验判断，而是有一个标准化流程确保不遗漏关键风险项。这和 code-review 的思路一模一样：用流程保证不遗漏，而不是依赖个人记忆力。

---

## 检查清单

- [ ] 写了完整的 SKILL.md（frontmatter + 步骤 + 验收标准 + 约束）
- [ ] 加了辅助文件（checklist + severity + analyze.py），并在 SKILL.md 里引用
- [ ] 知道两种触发方式：斜杠命令手动触发 + description 自动匹配
- [ ] 会写 description（动词 + 做什么 + 输出什么）
- [ ] 写了 smoke test，能对比有/无 Skill 的效果差异
- [ ] 辅助文件控制在 3-5 个以内
- [ ] Skill 内容和 CLAUDE.md 不重复

---

## 下课预告

Day 03 搞清了 Skills 是什么，Day 04 实战写了一个完整的 Skill。明天 Day 05 换个视角——不再是一个 Agent 自己的事，而是**Agent 和 Agent 之间怎么通信**。我们将学习 A2A（Agent-to-Agent）和 ACP（Agent Communication Protocol）协议——这是让多个 Agent 协作的标准。你在 Week 07 学过 Subagents（主从模式），A2A/ACP 是另一种思路：Agent 之间是平等的，通过标准协议互相发现、协商、协作。两个 Agent 怎么"握手"？怎么"委托任务"？怎么"回报结果"？明天见。
