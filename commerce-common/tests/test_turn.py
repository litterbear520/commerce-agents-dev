# 项目中对应 commerce-common/tests/test_turn.py

import json
import logging
from types import SimpleNamespace

from anthropic.types import Message, TextBlock, Usage

from commerce_common.streaming import AgentEvent, ToolOutcome
from commerce_common.turn import (
    CLEARED_RESULT,
    StreamedRound,
    accumulate_usage,
    compact_history,
    fetched,
    latest_exchange,
    latest_user_text,
    log_model_call,
    outcome_events,
    prompt_tokens,
    round_closes_turn,
    session_tag,
    tool_result_block,
    transcript_text,
    usage_totals,
)

REMINDER = "调用方提醒：先暂存。"
CONVERSATION = [
    {"role": "user", "content": "第一个问题"},
    {"role": "assistant", "content": [{"type": "text", "text": "第一个回答"}]},
    {"role": "user", "content": [{"type": "text", "text": "把价格降下来"}]},
    {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "x", "input": {}}]},
    {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]},
    {"role": "assistant", "content": [{"type": "text", "text": "要我改吗？"}]},
    {"role": "user", "content": [{"type": "text", "text": REMINDER}]},
    {"role": "assistant", "content": [{"type": "text", "text": "已暂存"}]},
]


def test_latest_user_text_skips_tool_results_and_host_messages():
    assert latest_user_text(CONVERSATION[:1]) == "第一个问题"
    assert latest_user_text(CONVERSATION[:5]) == "把价格降下来"
    assert latest_user_text(CONVERSATION, {REMINDER}) == "把价格降下来"
    assert latest_user_text([{"role": "user", "content": [{"type": "image"}]}]) == ""
    assert latest_user_text([]) == ""


def test_latest_exchange_starts_at_the_users_own_message_on_a_reminded_turn():
    assert latest_exchange(CONVERSATION, {REMINDER}) == CONVERSATION[2:]
    assert latest_exchange(CONVERSATION) == CONVERSATION[6:]


def test_transcript_text_keeps_user_and_assistant_lines_only():
    lines = transcript_text(latest_exchange(CONVERSATION, {REMINDER}), {REMINDER}).splitlines()
    assert lines == ["user: 把价格降下来", "assistant: 要我改吗？", "assistant: 已暂存"]


DISPLAYED = "已展示。"
PRESENTS = {"present_products", "present_suggestions"}
CHIPS = (
    "present_suggestions",
    ToolOutcome(DISPLAYED, [AgentEvent.ui("suggestions", {"suggestions": ["比较一下"]})]),
)


def _clean(name: str, outcome: ToolOutcome) -> bool:
    """执行器的判断规则：展示类调用，没有被拒绝，没有追加备注。"""
    return name in PRESENTS and not outcome.refused and outcome.result_text == DISPLAYED


def _shown(text: str = DISPLAYED) -> ToolOutcome:
    return ToolOutcome(text, [AgentEvent.ui("products", {"items": []})])


def test_only_a_clean_round_with_the_chips_call_closes_the_turn():
    def closes(*calls: tuple[str, ToolOutcome]) -> bool:
        return round_closes_turn(list(calls), _clean)

    card = ("present_products", _shown())
    assert closes(card, CHIPS) and closes(CHIPS) and closes(card, card, CHIPS)
    assert not closes() and not closes(card)
    # stage 调用、追加备注、读取调用、拒绝、建议按钮失败——都留给模型来结束。
    assert not closes(("stage_price_update", ToolOutcome("<data>已暂存</data>")), CHIPS)
    assert not closes(("present_products", _shown(f"{DISPLAYED} 未展示：p-9。")), CHIPS)
    assert not closes(CHIPS, ("search_products", ToolOutcome("<data>[]</data>")))
    assert not closes(CHIPS, ("present_products", ToolOutcome.error("参数无效")))
    assert not closes(CHIPS, ("present_products", ToolOutcome.held("provenance", "已拦截。")))
    assert not closes(card, ("present_suggestions", ToolOutcome.error("参数无效")))


def _event(kind: str, index: int, **fields) -> SimpleNamespace:
    return SimpleNamespace(type=kind, index=index, **fields)


def _start(index: int, **block) -> SimpleNamespace:
    content = SimpleNamespace(**block, model_dump=lambda **_: dict(block))
    return _event("content_block_start", index, content_block=content)


def _delta(index: int, **delta) -> SimpleNamespace:
    return _event("content_block_delta", index, delta=SimpleNamespace(**delta))


def test_a_streamed_round_rebuilds_what_arrived_and_marks_the_call_that_never_parsed():
    streamed = StreamedRound()
    events = [
        _start(0, type="thinking", thinking="", signature=""),
        _delta(0, type="thinking_delta", thinking="有两款合适。"),
        _delta(0, type="signature_delta", signature="sig-1"),
        _event("content_block_stop", 0),
        _start(1, type="text", text=""),
        _delta(1, type="text_delta", text="给你列出来了。"),
        _event("content_block_stop", 1),
        _start(2, type="tool_use", id="tu-1", name="search_products", input={}),
        _delta(2, type="input_json_delta", partial_json='{"query": "tent"}'),
        _event("content_block_stop", 2),
        _start(3, type="tool_use", id="tu-2", name="present_products", input={}),
        _delta(3, type="input_json_delta", partial_json='{"picks": [不是 JSON'),
    ]
    touched = [streamed.feed(event) for event in events]
    assert [t.id if t else None for t in touched][7:] == ["tu-1", "tu-1", "tu-1", "tu-2", "tu-2"]
    assert streamed.tool_open()
    message, tool_uses, unreadable = streamed.salvaged()
    assert message["role"] == "assistant"
    assert message["content"] == [
        {"type": "thinking", "thinking": "有两款合适。", "signature": "sig-1"},
        {"type": "text", "text": "给你列出来了。"},
        {"type": "tool_use", "id": "tu-1", "name": "search_products", "input": {"query": "tent"}},
        {"type": "tool_use", "id": "tu-2", "name": "present_products", "input": {}},
    ]
    assert [(t.name, t.input) for t in tool_uses] == [
        ("search_products", {"query": "tent"}),
        ("present_products", {}),
    ]
    assert unreadable == {"tu-2"}
    # 所有工具块关闭后就没有 open 的了，空文本块被丢弃。
    closed = StreamedRound()
    for event in [_start(0, type="text", text=""), *events[7:10]]:
        closed.feed(event)
    assert not closed.tool_open()
    message, _, unreadable = closed.salvaged()
    assert [block["type"] for block in message["content"]] == ["tool_use"] and not unreadable


def test_a_streamed_round_keeps_server_tool_blocks_and_counts_the_streams_usage():
    """abandoned 的 web search 轮次用它的服务端块（不分派、citations 同正常轮次一样排除）
    重放，token 计入用量。"""
    streamed = StreamedRound()
    started = SimpleNamespace(input_tokens=90, cache_read_input_tokens=30, output_tokens=1)
    result = {"type": "web_search_tool_result", "tool_use_id": "ws", "content": []}
    events = [
        SimpleNamespace(type="message_start", message=SimpleNamespace(usage=started)),
        _start(0, type="server_tool_use", id="ws", name="web_search", input={}),
        _delta(0, type="input_json_delta", partial_json='{"query": "shoes"}'),
        _event("content_block_stop", 0),
        _start(1, **result),
        _event("content_block_stop", 1),
        _start(2, type="text", text=""),
        _delta(2, type="citations_delta", citation=SimpleNamespace(title="t")),
        _delta(2, type="text_delta", text="两款合适。"),
        _event("content_block_stop", 2),
        _start(3, type="tool_use", id="tu-1", name="present_products", input={}),
        _delta(3, type="input_json_delta", partial_json='{"picks": ['),
        SimpleNamespace(type="message_delta", usage=SimpleNamespace(output_tokens=40)),
    ]
    for event in events:
        streamed.feed(event)
    message, tool_uses, unreadable = streamed.salvaged()
    assert message["content"][:3] == [
        {"type": "server_tool_use", "id": "ws", "name": "web_search", "input": {"query": "shoes"}},
        result,
        {"type": "text", "text": "两款合适。"},
    ]
    assert [t.name for t in tool_uses] == ["present_products"] and unreadable == {"tu-1"}
    totals = usage_totals()
    accumulate_usage(totals, streamed)
    counted = {"input_tokens": 90, "output_tokens": 40, "cache_read_input_tokens": 30}
    assert totals == usage_totals() | counted and prompt_tokens(streamed) == 120


class _Backend:
    async def get_cart(self):
        return "cart"

    async def get_preferences(self):
        raise ConnectionError("偏好服务宕机")


async def test_fetched_returns_none_for_a_failed_prefetch_and_logs_it(caplog):
    with caplog.at_level(logging.WARNING, logger="commerce_common.turn"):
        assert await fetched(_Backend().get_cart()) == "cart"
        assert await fetched(_Backend().get_preferences()) is None
    (record,) = [r for r in caplog.records if r.name == "commerce_common.turn"]
    assert record.levelno == logging.WARNING
    assert "_Backend.get_preferences" in record.getMessage()
    assert record.exc_info is not None and isinstance(record.exc_info[1], ConnectionError)


def test_outcome_events_stamp_ui_events_and_summarize_long_results():
    outcome = ToolOutcome("x" * 500, [AgentEvent.ui("card", {"a": 1}), AgentEvent.cart_update({})])
    ui, cart, result = outcome_events("tool", "t1", outcome)
    assert ui.data["stream_id"] == "t1" and "stream_id" not in cart.data
    assert result.data["summary"] == "ok" and result.data["excerpt"] == "x" * 500
    assert result.data["status"] == "ok"


def test_held_and_failed_results_keep_their_text():
    (held,) = outcome_events("tool", "t1", ToolOutcome.held("provenance", "h" * 300))
    assert held.data == {
        "tool": "tool",
        "id": "t1",
        "summary": "h" * 300,
        "is_error": False,
        "status": "blocked",
        "reason": "provenance",
    }
    (failed,) = outcome_events("tool", "t2", ToolOutcome.error("no"))
    assert failed.data["status"] == "error" and failed.data["is_error"] is True
    assert tool_result_block("t2", ToolOutcome.error("no")) == {
        "type": "tool_result",
        "tool_use_id": "t2",
        "content": "no",
        "is_error": True,
    }


# ── 历史压缩 ──────────────────────────────────────────────────


def _long_conversation(rounds: int) -> list[dict]:
    messages: list[dict] = [{"role": "user", "content": "找帐篷"}]
    for index in range(rounds):
        call_id = f"t{index}"
        messages += [
            {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": call_id, "name": "x", "input": {}}],
            },
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": call_id, "content": "x" * 2000}],
            },
        ]
    messages.append({"role": "user", "content": "再来个炉子"})
    return messages


def _result_bodies(messages: list[dict]) -> list[str]:
    return [
        block["content"]
        for message in messages
        if isinstance(message["content"], list)
        for block in message["content"]
        if block["type"] == "tool_result"
    ]


def test_compaction_waits_for_the_prompt_to_reach_the_limit():
    messages = _long_conversation(4)
    before = [dict(message) for message in messages]
    assert compact_history(messages, 99_000, 100_000, "s-1") == 0
    assert compact_history(messages, 500_000, 0, "s-1") == 0
    assert messages == before


def test_compaction_clears_the_oldest_results_until_the_conversation_is_half_its_size(caplog):
    messages = _long_conversation(6)
    size = len(json.dumps(messages))
    with caplog.at_level(logging.INFO, logger="commerce_common.turn"):
        cleared = compact_history(messages, 100_000, 100_000, "s-1")
    bodies = _result_bodies(messages)
    assert cleared == 4 and bodies == [CLEARED_RESULT] * 4 + ["x" * 2000] * 2
    assert len(json.dumps(messages)) <= size // 2
    assert messages[0]["content"] == "找帐篷" and messages[-1]["content"] == "再来个炉子"
    (record,) = caplog.records
    assert (
        f"session={session_tag('s-1')} prompt_tokens=100000 results_cleared=4"
        in record.getMessage()
    )


def test_prompt_tokens_counts_everything_the_model_was_given():
    assert prompt_tokens(_message()) == 240


# ── 用量与模型调用日志 ────────────────────────────────────────


def _message() -> Message:
    return Message(
        id="msg_1",
        type="message",
        role="assistant",
        model="claude-test",
        content=[TextBlock(type="text", text="给你挑好了。")],
        stop_reason="end_turn",
        stop_sequence=None,
        usage=Usage(
            input_tokens=120,
            output_tokens=8,
            cache_read_input_tokens=100,
            cache_creation_input_tokens=20,
        ),
    )


def test_usage_accumulates_all_four_counters():
    totals = usage_totals()
    accumulate_usage(totals, _message())
    accumulate_usage(totals, _message())
    assert totals == {
        "input_tokens": 240,
        "output_tokens": 16,
        "cache_read_input_tokens": 200,
        "cache_creation_input_tokens": 40,
    }


def test_the_model_call_record_lands_on_the_callers_logger_with_bodies_at_debug(caplog):
    caller = logging.getLogger("shopping_agent_runtime.orchestrator")
    request = {"model": "claude-test", "messages": [{"role": "user", "content": "帐篷"}]}
    with caplog.at_level(logging.INFO, logger=caller.name):
        log_model_call(caller, request, _message(), 0.0, "s-1", round=0)
    (info,) = caplog.records
    assert info.name == caller.name
    line = info.getMessage()
    assert f"session={session_tag('s-1')} round=0 model=claude-test stop=end_turn" in line
    assert "s-1" not in line
    assert "input=120 cache_read=100 cache_write=20 output=8 elapsed_ms=" in line
    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger=caller.name):
        log_model_call(caller, request, _message(), 0.0, "s-1", round=0)
    _, sent, received = caplog.records
    assert '"content": "帐篷"' in sent.getMessage() and "给你挑好了。" in received.getMessage()


def test_session_tag_is_stable_short_and_not_the_id():
    tag = session_tag("sess-credential-1")
    assert tag == session_tag("sess-credential-1") and len(tag) == 12
    assert tag not in "sess-credential-1" and session_tag(None) == "-"
