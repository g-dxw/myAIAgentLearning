#!/usr/bin/env python3
"""
Tool Design — Agent Tool Engineering 实战演示 (Day 05)
======================================================

本文件演示 AI Agent Tool 设计的六大原则、Schema 设计对比、
搜索工具实现、工具粒度决策树，以及安全注意事项。

在终端直接运行:
    python tool_design.py

即可看到所有演示模块的输出。
"""

import json
import urllib.parse
import urllib.request
import ssl
from typing import Optional

# ╔══════════════════════════════════════════════════════════════╗
# ║  一、坏工具 vs 好工具的 Schema 对比（注释说明）              ║
# ╚══════════════════════════════════════════════════════════════╝

# ── 反例："坏工具" Schema ──────────────────────────────────────
BAD_TOOL_SCHEMA = {
    "name": "search",
    "description": "搜索东西",
    "parameters": {
        "type": "object",
        "properties": {
            "q": {"type": "string", "description": "关键词"},
        },
        "required": ["q"],
    },
}
"""
❌ 坏工具的问题:
  1. 名称模糊 — "search" 搜什么？Web / DB / 代码？
  2. 描述过于笼统 — "搜索东西" 完全没说明行为边界
  3. 参数命名糟糕 — "q" 让 LLM 难以理解语义
  4. 缺少类型约束 — 未限制最大长度、必填但无 validate
  5. 无错误处理契约 — 失败时返回什么？
  6. 无副作用声明 — 会调外部 API 吗？有网络开销吗？
"""

# ── 正例："好工具" Schema ──────────────────────────────────────
GOOD_TOOL_SCHEMA = {
    "name": "search_web",
    "description": (
        "通过 DuckDuckGo 搜索互联网，返回网页标题、链接和摘要。"
        "适用于查询实时信息、新闻、文档等。当 Bing 退回到限流时自动降级。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "搜索关键词（UTF-8，最长 200 字符）",
                "maxLength": 200,
            },
            "max_results": {
                "type": "integer",
                "description": "返回结果条数（1-10，默认 5）",
                "default": 5,
                "minimum": 1,
                "maximum": 10,
            },
            "safe_search": {
                "type": "boolean",
                "description": "是否开启安全搜索过滤（默认 True）",
                "default": True,
            },
        },
        "required": ["query"],
    },
}
"""
✅ 好工具的设计要点:
  1. 名称自解释 — "search_web" 明确表示搜索互联网
  2. 描述充实 — 说清用途、数据来源、备选方案
  3. 参数名清晰 — "query" 而非 "q"，"max_results" 而非 "n"
  4. 约束完整 — maxLength / minimum / maximum / default
  5. 安全设计 — safe_search 默认开启，LLM 可自主选择关闭
  6. 契约明确 — 后续代码定义返回结构，调用方知道预期输出
"""


# ╔══════════════════════════════════════════════════════════════╗
# ║  二、search_web(): DuckDuckGo + Bing 回退搜索               ║
# ╚══════════════════════════════════════════════════════════════╝

def search_web(
    query: str,
    max_results: int = 5,
    safe_search: bool = True,
) -> list[dict]:
    """
    基于 DuckDuckGo Lite API 的 Web 搜索，Bing 作为回退。

    策略说明:
      1. 首选 DuckDuckGo (无 API Key，隐私友好)
      2. 如果 DuckDuckGo 限流或超时，自动降级到 Bing 搜索
      3. 两者均失败时，返回明确错误消息给 LLM

    Returns:
        list[dict]: 每个 dict 包含 title, url, snippet 三个字段。
        搜索失败时返回 [{"error": "..."}]。
    """
    results = _search_duckduckgo(query, max_results)
    if results and not results[0].get("error"):
        return results

    print("  ⚠  DuckDuckGo 不可用，降级到 Bing...")
    results = _search_bing(query, max_results)
    if results and not results[0].get("error"):
        return results

    return [{"error": "所有搜索引擎均不可用，请稍后重试。"}]


def _search_duckduckgo(query: str, max_results: int) -> list[dict]:
    """DuckDuckGo Lite API 搜索（无需 Key）"""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    params = urllib.parse.urlencode({"q": query, "format": "json"})
    url = f"https://lite.duckduckgo.com/lite/?{params}"

    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36"
                ),
            },
        )
        with urllib.request.urlopen(req, timeout=5, context=ctx) as resp:
            data = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return [{"error": f"DuckDuckGo 请求失败: {e}"}]

    # DDG Lite 返回 HTML，需简单解析 <a> 标签提取结果
    results = []
    import re
    # 匹配结果的简单模式（DuckDuckGo Lite HTML 结构）
    lines = data.splitlines()
    for i, line in enumerate(lines):
        if 'class="result-link"' in line or '<a ' in line and 'href' in line:
            match = re.search(r'href="([^"]+)"', line)
            if match:
                url = match.group(1)
                # 获取结果标题（可能在下一行）
                title = ""
                for j in range(i + 1, min(i + 4, len(lines))):
                    t = re.sub(r'<[^>]+>', '', lines[j]).strip()
                    if t:
                        title = t
                        break
                results.append({
                    "title": title or "(无标题)",
                    "url": url,
                    "snippet": f"DuckDuckGo 结果: {title}",
                })
            if len(results) >= max_results:
                break

    return results if results else [{"error": "DuckDuckGo 无结果返回"}]


def _search_bing(query: str, max_results: int) -> list[dict]:
    """Bing 搜索回退（解析 HTML 提取结果）"""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    encoded = urllib.parse.quote(query)
    url = f"https://www.bing.com/search?q={encoded}&count={max_results}"

    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        )
        with urllib.request.urlopen(req, timeout=5, context=ctx) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return [{"error": f"Bing 请求失败: {e}"}]

    # 粗解析 Bing 搜索结果 (HTML 片段)
    results = []
    import re
    # Bing 结果通常在 <li class="b_algo"> 中
    blocks = re.split(r'<li[^>]*class="b_algo"[^>]*>', html)
    for block in blocks[1:]:  # 跳过第一个(<li>之前的内容)
        # 提取标题
        title_match = re.search(r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', block, re.DOTALL)
        if title_match:
            url = title_match.group(1)
            title = re.sub(r'<[^>]+>', '', title_match.group(2)).strip()
            # 提取摘要
            snippet_match = re.search(
                r'<p[^>]*>(.*?)</p>', block, re.DOTALL
            )
            snippet = ""
            if snippet_match:
                snippet = re.sub(r'<[^>]+>', '', snippet_match.group(1)).strip()
            results.append({
                "title": title or "(无标题)",
                "url": url,
                "snippet": snippet,
            })
        if len(results) >= max_results:
            break

    return results if results else [{"error": "Bing 无结果返回"}]


# ╔══════════════════════════════════════════════════════════════╗
# ║  三、六大设计原则 — 代码演示                                  ║
# ╚══════════════════════════════════════════════════════════════╝

# ── 原则 1: 单一职责（Single Responsibility） ──────────────────
"""
✅ 正确: 每个 Tool 只做一件事
  - search_web()         → 只做 Web 搜索
  - calculator()         → 只做数学计算
  - read_file()          → 只做文件读取

❌ 错误: 一个 Tool 做多件事
  - process_data(action='search|calc|read')  → 违反单一职责
"""


def calculator(expression: str) -> dict:
    """安全计算器 — 单一职责：仅做数学计算"""
    allowed = set("0123456789+-*/(). ")
    if not all(c in allowed for c in expression):
        return {"error": "表达式包含非法字符"}
    try:
        result = eval(expression, {"__builtins__": {}}, {})
        return {"result": result}
    except Exception as e:
        return {"error": f"计算失败: {e}"}


# ── 原则 2: 可验证 Schema（Verifiable Schema） ─────────────────
"""
✅ 正确: Schema 约束完整，LLM 知道参数边界
  见上方 GOOD_TOOL_SCHEMA，包含 maxLength / minimum / maximum / default

❌ 错误: Schema 缺乏验证信息
  - "query": {"type": "string"}  ← 没有 maxLength，LLM 可能传入过长文本
  - 没有 default 值，LLM 每次都要显式传参
"""


def validate_tool_call(schema: dict, arguments: dict) -> tuple[bool, str]:
    """演示参数的 Schema 校验逻辑"""
    props = schema.get("parameters", {}).get("properties", {})
    for key, value in arguments.items():
        spec = props.get(key, {})
        if isinstance(value, str) and "maxLength" in spec:
            if len(value) > spec["maxLength"]:
                return False, f"参数 '{key}' 超长 ({len(value)} > {spec['maxLength']})"
        if isinstance(value, (int, float)):
            if "minimum" in spec and value < spec["minimum"]:
                return False, f"参数 '{key}' 过小 ({value} < {spec['minimum']})"
            if "maximum" in spec and value > spec["maximum"]:
                return False, f"参数 '{key}' 过大 ({value} > {spec['maximum']})"
    return True, "校验通过"


# ── 原则 3: 优雅降级（Graceful Degradation） ──────────────────
"""
✅ 正确: 主方案失败时自动降级
  search_web() 的实现展示了:
    1. DuckDuckGo → 成功则直接返回
    2. DuckDuckGo 失败 → 降级到 Bing
    3. Bing 也失败 → 返回明确错误
    永不崩溃，永远返回可用格式

❌ 错误: 单点故障直接崩溃
  def search():
      return requests.get("https://api.example.com/search").json()
  # 如果 api.example.com 挂了 → 整个 Agent 卡死
"""


def graceful_fallback_demo():
    """演示优雅降级：即使计算器出错也返回友好消息"""
    risky = ["1+1", "10/0", "2**10"]
    for expr in risky:
        result = calculator(expr)
        status = "✅" if "result" in result else "⚠️"
        print(f"  {status}  calculator('{expr}') → {result}")


# ── 原则 4: 有意义的错误消息（Meaningful Errors） ─────────────
"""
✅ 正确:
  {"error": "参数 'query' 超长 (250 > 200)，请缩短搜索关键词"}

❌ 错误:
  {"error": "Error: 500"}           ← LLM 不知道怎么办
  {"error": "Something went wrong"}  ← 无信息量
"""


def meaningful_error_demo():
    """好错误 vs 坏错误"""
    bad_errors = [
        {"error": "Error 500"},
        {"error": "Failed"},
        {"error": None},
    ]
    good_errors = [
        {"error": "搜索查询超长 (250 字符 > 200 上限)，请精简关键词"},
        {"error": "网络请求超时 (5s)，请降级到本地缓存或稍后重试"},
        {"error": "搜索 'NoneType' 包含非法字符，请移除特殊符号"},
    ]
    print("  ❌ 坏错误示例: LLM 看到后不知道如何处理")
    for e in bad_errors:
        print(f"     {e}")
    print("  ✅ 好错误示例: LLM 看到后可自主采取修复动作")
    for e in good_errors:
        print(f"     {e}")


# ── 原则 5: 上下文长度意识（Context Aware） ──────────────────
"""
✅ 正确: 返回值有长度上限，附带截断标记
  max_chars=2000，超出时截断并标记

❌ 错误: 返回值可能塞爆 Context Window
  一次性返回 50000 字符的搜索结果 → 摧毁后续对话
"""


def truncate_for_context(data: list[dict], max_chars: int = 2000) -> list[dict]:
    """截断过长的返回结果，保护 Context Window"""
    total = 0
    truncated = []
    for item in data:
        item_str = json.dumps(item, ensure_ascii=False)
        if total + len(item_str) > max_chars:
            truncated.append({
                "title": "(截断)",
                "url": "",
                "snippet": f"结果过长，已截断。剩余 {len(data) - len(truncated)} 条未返回。",
            })
            break
        truncated.append(item)
        total += len(item_str)
    return truncated


# ── 原则 6: 可组合性（Composable） ────────────────────────────
"""
✅ 正确: Tool 输出可自然作为另一个 Tool 的输入
  search_web("Python Agent") 返回 url 列表
  → 把 url 传给 extract_web_content(url) 进行内容提取
  → 再把内容传给 summarize(text) 进行摘要

❌ 错误: 输出格式特殊，无法链式调用
  search_web() 返回 {"html": "<div>..."}  ← 其他 Tool 读不了
"""


def extract_web_content(url: str) -> dict:
    """复合工具：接收 search_web() 的 url 作为输入"""
    return {"url": url, "content": f"[模拟] 从 {url} 提取的内容..."}


def summarize(text: str) -> dict:
    """复合工具：接收 extract_web_content() 的 content 作为输入"""
    return {"summary": f"[模拟摘要] {text[:50]}..."}


def composability_demo():
    """演示 Tool 链式组合"""
    print("  🔗 Tool 链: search_web → extract_web_content → summarize")
    search_result = search_web("Python Agent Tool Design", max_results=2)
    print(f"     步骤1: search_web → {len(search_result)} 条结果")
    if search_result and "url" in search_result[0]:
        extracted = extract_web_content(search_result[0]["url"])
        print(f"     步骤2: extract_web_content → {extracted['content'][:40]}...")
        summary = summarize(extracted["content"])
        print(f"     步骤3: summarize → {summary['summary']}")


# ╔══════════════════════════════════════════════════════════════╗
# ║  四、工具粒度决策树（注释说明）                              ║
# ╚══════════════════════════════════════════════════════════════╝

TOOL_GRANULARITY_DECISION_TREE = """
# 工具粒度决策树 — 如何决定拆几个 Tool？

用以下决策树决定一个功能应拆为多少个 Tool：

## 决策流程

  问: 这个操作需要 LLM 做决策吗？
  ├── 否 → 不该是 Tool（应是内部函数 / 代码块）
  │
  └── 是 → 问: 参数中有"动作选择"类字段吗？
      ├── 是 → 危险信号！考虑拆分
      │    例如: tool(action="search|calculate|translate")
      │    → 拆为三个独立的 Tool
      │
      └── 否 → 问: 这个操作的输入 / 输出格式统一吗？
          ├── 否 → 考虑拆分
          │    例如: read_file(格式:文本) vs analyze_image(格式:图像)
          │    → read_file 和 analyze_image 应分开
          │
          └── 是 → 问: 和现有 Tool 的职责耦合吗？
              ├── 是 → 保持为一个 Tool（高内聚）
              │    例如: search_web(query, max_results, safe_search)
              │    → 三个参数都服务于 "搜索互联网" 这一职责
              │
              └── 否 → 保持独立
                   例如: search_web() 和 calculator()
                   → 完全不耦合，各自独立

## 经验法则

  - 一个 Agent 通常拥有 5-15 个 Tool
  - 少于 5 个 → LLM 缺乏能力边界，可能导致幻觉
  - 多于 15 个 → Token 开销过大，LLM 选择困难
  - 参数不多于 5 个（超过说明职责可能过重）

## 反例快查

  ❌ "超级 Tool": tool(name="do_everything", params={action, data})
     → 拆分为多个单一职责 Tool

  ❌ "碎屑 Tool": tool(name="add", ...), tool(name="subtract", ...)
     → 合并为 calculator(expression) 更合理

  ✅ 平衡点: search_web, calculator, read_file, write_file,
     extract_content, summarize, translate, send_email
"""


# ╔══════════════════════════════════════════════════════════════╗
# ║  五、安全注意事项                                            ║
# ╚══════════════════════════════════════════════════════════════╝

SAFETY_NOTES = """
# 🔒 Tool 安全设计清单

## 1. 输入净化 (Input Sanitization)
   - calculator() 中白名单字符集 "0123456789+-*/(). "
   - 拒绝包含 __import__、os、eval 嵌套等危险模式
   - 始终使用白名单（allowlist）而非黑名单（blocklist）

## 2. 超时控制 (Timeout Control)
   - 所有网络调用设置合理的超时（如 5-10s）
   - 防止恶意输入导致无限等待
   - 示例: urllib.request.urlopen(..., timeout=5)

## 3. 限流保护 (Rate Limiting)
   - 高频调用同一外部 API 时应加入 delay 或 token bucket
   - 防止被外部服务封禁 IP

## 4. 副作用声明 (Side Effect Declaration)
   - Tool description 中明确声明副作用:
     "此工具会发起外部网络请求" / "此工具会修改磁盘文件"

## 5. 敏感信息过滤 (Sensitive Data Filtering)
   - Tool 输出中过滤 API Key、Token、密码、内网 IP
   - 日志中同样需要脱敏

## 6. 权限最小化 (Least Privilege)
   - 文件操作类 Tool 应限定读写目录范围
   - 数据库类 Tool 应只暴露只读查询
   - Shell 执行类 Tool 应极度谨慎（最好避免）

## 7. 拒绝服务防护 (DoS Protection)
   - 设置 max_results=10 上限，防止返回海量数据
   - 设置 max_chars 截断保护 Context Window

## 8. 用户确认 (User Confirmation)
   - 写操作、删除操作、发消息操作应要求用户二次确认
   - 可在 Tool 设计层面加入 confirm_required 标志
"""


# ╔══════════════════════════════════════════════════════════════╗
# ║  六、if __name__ 演示                                        ║
# ╚══════════════════════════════════════════════════════════════╝

def demo_all():
    """运行所有演示模块"""
    print("=" * 70)
    print("  🛠  Tool 设计演示 — Day 05")
    print("=" * 70)

    # 1. Schema 对比
    print("\n" + "─" * 70)
    print("  【1】坏工具 vs 好工具 Schema 对比")
    print("─" * 70)
    print("\n  ❌ 坏工具 Schema:")
    print(f"     {json.dumps(BAD_TOOL_SCHEMA, ensure_ascii=False, indent=4)}")
    print("\n  ✅ 好工具 Schema:")
    print(f"     {json.dumps(GOOD_TOOL_SCHEMA, ensure_ascii=False, indent=4)}")
    print("\n  💡 详见代码中的 BAD_TOOL_SCHEMA / GOOD_TOOL_SCHEMA 及注释。")

    # 2. 搜索演示
    print("\n" + "─" * 70)
    print("  【2】search_web() — DuckDuckGo + Bing 回退搜索")
    print("─" * 70)
    print("\n  正在搜索 'Python Agent framework'...")
    results = search_web("Python Agent framework", max_results=3)
    for i, r in enumerate(results, 1):
        if "error" in r:
            print(f"  ⚠  结果 {i}: {r['error']}")
        else:
            print(f"  ✅ 结果 {i}: {r['title']}")
            print(f"     URL: {r['url']}")
            print(f"     摘要: {r['snippet'][:80]}...")

    # 3. 六原则演示
    print("\n" + "─" * 70)
    print("  【3】六大设计原则代码演示")
    print("─" * 70)

    print("\n  📌 原则1 — 单一职责: calculator()")
    print(f"     calculator('3 * (4 + 5)') → {calculator('3 * (4 + 5)')}")
    print(f"     calculator('10 + 20')      → {calculator('10 + 20')}")
    dangerous_input = '__import__("os").system("rm -rf /")'
    print(f"     calculator(dangerous_input) → {calculator(dangerous_input)}")

    print("\n  📌 原则2 — 可验证 Schema: validate_tool_call()")
    valid, msg = validate_tool_call(
        GOOD_TOOL_SCHEMA, {"query": "hello", "max_results": 3}
    )
    print(f"     正常调用 → {valid}, {msg}")
    valid, msg = validate_tool_call(
        GOOD_TOOL_SCHEMA, {"query": "x" * 300, "max_results": 3}
    )
    print(f"     超长调用 → {valid}, {msg}")
    valid, msg = validate_tool_call(
        GOOD_TOOL_SCHEMA, {"query": "hello", "max_results": 99}
    )
    print(f"     超量调用 → {valid}, {msg}")

    print("\n  📌 原则3 — 优雅降级: graceful_fallback_demo()")
    graceful_fallback_demo()

    print("\n  📌 原则4 — 有意义的错误消息")
    meaningful_error_demo()

    print("\n  📌 原则5 — 上下文长度意识: truncate_for_context()")
    long_data = [{"title": f"结果{i}", "url": f"http://example.com/{i}",
                   "snippet": "A" * 500} for i in range(20)]
    truncated = truncate_for_context(long_data, max_chars=800)
    print(f"     原始 {len(long_data)} 条 → 截断后 {len(truncated)} 条")
    if truncated:
        print(f"     最后一条: {truncated[-1]}")

    print("\n  📌 原则6 — 可组合性: Tool 链式调用")
    composability_demo()

    # 4. 粒度决策树
    print("\n" + "─" * 70)
    print("  【4】工具粒度决策树")
    print("─" * 70)
    print(TOOL_GRANULARITY_DECISION_TREE)

    # 5. 安全注意事项
    print("─" * 70)
    print("  【5】安全注意事项")
    print("─" * 70)
    print(SAFETY_NOTES)

    # 6. 结束
    print("=" * 70)
    print("  ✅ 演示完毕！所有模块已运行。")
    print("=" * 70)


if __name__ == "__main__":
    demo_all()
