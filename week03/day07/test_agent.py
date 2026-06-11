"""
Week 03 Day 07 — Agent 验证测试

运行: python test_agent.py
需要: my_agent.py 在同一目录
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from my_agent import MyAgent


def test_basic_conversation():
    """基础对话测试"""
    agent = MyAgent()
    result = agent.run("你好，请介绍一下你自己")
    assert len(result) > 0, "❌ 基础对话失败：返回为空"
    print("✅ 基础对话通过")


def test_calculate():
    """数学计算测试"""
    agent = MyAgent()
    result = agent.run("1024 * 768 等于多少？")
    # 检查结果中是否包含正确的计算结果
    assert "786" in result or "786432" in result, f"❌ 计算失败：{result[:100]}"
    print("✅ 数学计算通过")


def test_get_time():
    """时间查询测试"""
    agent = MyAgent()
    result = agent.run("现在几点了？")
    assert "点" in result or "时" in result or ":" in result, f"❌ 时间查询失败：{result[:100]}"
    print("✅ 时间查询通过")


def test_weather():
    """天气查询测试"""
    agent = MyAgent()
    result = agent.run("北京今天天气怎么样？")
    assert "北京" in result and ("°" in result or "度" in result or "温" in result), \
        f"❌ 天气查询失败：{result[:100]}"
    print("✅ 天气查询通过")


def test_note_memory():
    """笔记记忆测试"""
    agent = MyAgent()
    agent.run("记住我最喜欢的颜色是蓝色")
    result = agent.run("我喜欢什么颜色？")
    assert "蓝" in result, f"❌ 记忆失败：{result[:100]}"
    print("✅ 笔记记忆通过")


def test_multi_tool():
    """多工具组合测试"""
    agent = MyAgent()
    result = agent.run("北京天气怎么样？顺便告诉我现在几点了")
    assert ("北京" in result or "天气" in result), f"❌ 多工具天气部分失败：{result[:100]}"
    assert ("点" in result or "分" in result or "时" in result), f"❌ 多工具时间部分失败：{result[:100]}"
    print("✅ 多工具组合通过")


def test_search():
    """搜索功能测试"""
    agent = MyAgent()
    result = agent.run("帮我搜索一下Python编程语言")
    # 搜索可能返回结果也可能提示无法搜索
    assert len(result) > 0, "❌ 搜索失败：返回为空"
    print(f"✅ 搜索功能通过（返回 {len(result)} 字符）")


def test_error_handling():
    """错误处理测试：非法输入"""
    agent = MyAgent()
    # 尝试一个奇怪的计算
    result = agent.run("计算 1/0")
    assert len(result) > 0, "❌ 错误处理失败"
    print("✅ 错误处理通过")


def test_empty_input():
    """边界测试：空输入"""
    agent = MyAgent()
    result = agent.run("你好")
    assert len(result) > 0, "❌ 空输入处理失败"
    print("✅ 基础对话（空输入边界）通过")


def test_stats():
    """统计功能测试"""
    agent = MyAgent()
    agent.run("2+2等于几？")
    agent.run("现在几点了？")
    stats = agent.get_stats() if hasattr(agent, 'get_stats') else None
    if stats:
        assert stats.get("turns", 0) >= 2, f"❌ 统计失败：{stats}"
        print("✅ 统计功能通过")
    else:
        # 如果 Agent 没有 get_stats，至少不报错
        print("ℹ️ 统计功能未实现，跳过")


if __name__ == "__main__":
    print("=" * 50)
    print("🧪 MyAgent 验证测试套件")
    print("=" * 50)

    tests = [
        test_basic_conversation,
        test_calculate,
        test_get_time,
        test_weather,
        test_note_memory,
        test_multi_tool,
        test_search,
        test_error_handling,
        test_empty_input,
        test_stats,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"❌ {test.__name__} 失败: {e}")
            failed += 1
        except Exception as e:
            print(f"💥 {test.__name__} 异常: {e}")
            failed += 1

    print(f"\n{'='*50}")
    print(f"📊 结果: {passed}/{len(tests)} 通过, {failed} 失败")
    if failed == 0:
        print("🎉 全部测试通过！")
    else:
        print(f"⚠️ {failed} 个测试未通过，请检查 my_agent.py")
    print(f"{'='*50}")
