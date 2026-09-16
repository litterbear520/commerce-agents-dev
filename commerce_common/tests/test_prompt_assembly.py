"""prompt_assembly 的测试：系统块结构、时钟渲染、工具缓存控制、滚动断点、消息合并。"""
# 项目中对应 commerce-common/tests/test_prompt_assembly.py
# 跳过 with_eager_input（Step 15 的即时分派才用到）

import copy
from datetime import datetime, timedelta, timezone

from commerce_common.prompt_assembly import (
    build_request_messages,
    build_system_blocks,
    context_clock,
    with_tool_cache_control,
)

CONTEXT = "# 会话上下文\n<data>{}</data>"


# ── 系统块 ──────────────────────────────────────────────────────────────


def test_system_is_the_marked_static_block_then_the_context():
    static, context = build_system_blocks("# 身份和规则", CONTEXT)
    assert static == {
        "type": "text",
        "text": "# 身份和规则",
        "cache_control": {"type": "ephemeral"},
    }
    assert context == {"type": "text", "text": CONTEXT}


# ── 时钟 ────────────────────────────────────────────────────────────────


def test_the_context_clock_is_the_hour_in_the_sessions_offset():
    tz_east8 = timezone(timedelta(hours=8))
    assert context_clock(datetime(2026, 9, 15, 14, 37, 12, tzinfo=tz_east8)) == (
        "2026-09-15T14:00+08:00"
    )
    # 同一小时内两次调用输出一样，动态上下文字节不变，缓存不失效
    assert context_clock(datetime(2026, 9, 15, 14, 2)) == context_clock(
        datetime(2026, 9, 15, 14, 58)
    )


# ── 工具缓存控制 ────────────────────────────────────────────────────────


def test_tool_cache_control_marks_only_the_last_tool_and_copies():
    tools = [
        {"name": "search_products", "input_schema": {"type": "object"}},
        {"name": "get_cart", "input_schema": {"type": "object"}},
    ]
    marked = with_tool_cache_control(tools)
    assert "cache_control" in marked[-1]
    assert all("cache_control" not in t for t in marked[:-1])
    # 原始列表不受影响
    assert "cache_control" not in tools[-1]


def test_tool_cache_control_empty_list_is_a_noop():
    assert with_tool_cache_control([]) == []


# ── 滚动断点 ────────────────────────────────────────────────────────────


def _grown_conversation() -> list[dict]:
    """一轮搜索对话：用户提问 → 助手回复 → 工具结果。"""
    return [
        {"role": "user", "content": "帮我找耳机"},
        {"role": "assistant", "content": [{"type": "text", "text": "好的，帮你搜两款。"}]},
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "tu-1", "content": "ok"},
                {"type": "tool_result", "tool_use_id": "tu-2", "content": "ok"},
            ],
        },
    ]


def _marked_blocks(request: list[dict]) -> list[dict]:
    """提取请求中所有带 cache_control 的 block。"""
    return [
        block
        for message in request
        for block in (message["content"] if isinstance(message["content"], list) else [])
        if isinstance(block, dict) and "cache_control" in block
    ]


def test_marker_on_the_newest_persisted_block_only():
    request = build_request_messages(_grown_conversation())
    results = request[-1]["content"]
    # 最后一个 block 有标记
    assert results[-1]["cache_control"] == {"type": "ephemeral"}
    assert results[-1]["tool_use_id"] == "tu-2"
    # 同一条消息的前面 block 没有标记
    assert "cache_control" not in results[0]
    # 前面的消息也没有标记
    assert "cache_control" not in request[1]["content"][0]
    # 第一条 user 消息保持字符串格式不变
    assert request[0] == {"role": "user", "content": "帮我找耳机"}
    assert len(request) == 3


def test_string_content_is_lifted_without_mutating_history():
    messages = _grown_conversation()[:2] + [{"role": "user", "content": "便宜点的？"}]
    request = build_request_messages(messages)
    assert request[-1]["content"] == [
        {"type": "text", "text": "便宜点的？", "cache_control": {"type": "ephemeral"}}
    ]
    # 原始历史不受影响
    assert messages[-1]["content"] == "便宜点的？"


def test_the_marker_rolls_forward_stripping_the_previous_one():
    earlier = build_request_messages(_grown_conversation())
    # 模拟：调用方把带标记的结果又传了进来
    later = build_request_messages(
        earlier
        + [
            {"role": "assistant", "content": [{"type": "text", "text": "第一款更轻。"}]},
            {"role": "user", "content": "便宜的那个"},
        ]
    )
    # 整个请求里只有一个标记，在最新消息上
    assert _marked_blocks(later) == [later[-1]["content"][0]]
    assert later[-1]["content"][0]["text"] == "便宜的那个"


def test_a_user_message_after_tool_results_goes_out_as_one_message():
    """连续两条 user 消息合并成一条。"""
    messages = _grown_conversation() + [{"role": "user", "content": "结账"}]
    snapshot = copy.deepcopy(messages)
    request = build_request_messages(messages)
    # 4 条消息合并成 3 条，原始历史不变
    assert len(request) == 3 and messages == snapshot
    content = request[-1]["content"]
    # 顺序：两个 tool_result 在前，合并进来的文本在后
    assert [block["type"] for block in content[:3]] == [
        "tool_result",
        "tool_result",
        "text",
    ]
    # 断点在最后一个 block 上
    assert _marked_blocks(request) == [content[-1]]


def test_a_bare_first_call_is_sent_unmarked_and_unchanged():
    messages = [{"role": "user", "content": "你好"}]
    assert build_request_messages(messages) == messages


def test_rolling_breakpoint_off_sends_the_messages_unmarked():
    request = build_request_messages(_grown_conversation(), rolling_breakpoint=False)
    assert request == _grown_conversation()


def test_empty_messages_are_a_noop():
    assert build_request_messages([]) == []
