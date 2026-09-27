"""两个轮次循环都要遵守的约定：数据锚定轮次的缓存字节与上下文块，会话时钟。"""
# 项目中对应 tests/test_turn_loop.py
# 省略：滚动断点、提前分派、强制文字回复、被拦截的结果、历史压缩、轮次写入和上报的记录，
# 以及 Loop 里对应这些用例的字段（后续按需补）

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from commerce_common.testing import FakeClient, text_message, tool_use_message
from commerce_common.types import ClockContext
from merchant_agent_runtime import MerchantAgent
from shopping_agent_runtime import ShoppingAgent


@dataclass(frozen=True)
class Loop:
    agent: type
    gated_turns: tuple[
        tuple[str, str, dict[str, Any], int], ...
    ]  # 文本、强制的工具、它的输入、模型调用次数
    ungated_turn: str
    dynamic_heading: str


ROLES = {
    "shopping": Loop(
        ShoppingAgent,
        (
            ("退货手续费是多少？", "search_policies", {"query": "退货手续费"}, 2),
            ("我的订单到哪了？", "get_orders", {}, 2),
            ("把 AR-1602 加进购物车", "get_product_details", {"product_id": "AR-1602"}, 2),
        ),
        "推荐 200 元以内的轻便帐篷",
        "# 会话上下文",
    ),
    "merchant": Loop(
        MerchantAgent,
        # 项目中这句还带一个改价的尾巴，触发跟进提醒、多一次调用（Step 20）
        (("上周的转化率怎么样？", "get_business_snapshot", {}, 2),),
        "今天早上有什么急事吗？",
        "# 商户上下文",
    ),
}


@pytest.fixture(params=list(ROLES))
def role(request) -> str:
    return request.param


@pytest.fixture
def loop(role) -> Loop:
    return ROLES[role]


@pytest.fixture
def turn(loop, backend, skills, config, state):
    """``turn(text 或 messages, responses, session=..., chunks=..., **config_updates)`` ->
    (模型调用, 事件)；传入的 messages 列表原地扩展。"""

    async def _turn(text: Any, responses: list, *, session: Any, chunks=None, **updates: Any):
        client = FakeClient(responses, chunks)
        agent = loop.agent(
            backend=backend, skills=skills, config=config.model_copy(update=updates), client=client
        )
        messages = text if isinstance(text, list) else [{"role": "user", "content": text}]
        events = [event async for event in agent.stream_turn(messages, session, state)]
        return client.calls, events

    return _turn


@pytest.fixture
def run(turn):
    async def _run(
        text: str, responses: list, *, session: Any, **updates: Any
    ) -> list[dict[str, Any]]:
        calls, _ = await turn(text, responses, session=session, **updates)
        return calls

    return _run


def _cached_bytes(call: dict[str, Any]) -> tuple[str, str]:
    return json.dumps(call["system"], sort_keys=True, default=str), json.dumps(
        call["tools"], sort_keys=True
    )


def _context_block(call: dict[str, Any]) -> str:
    """每次请求的上下文：第二个系统块，在静态块的缓存标记之后。"""
    static, context = call["system"]
    assert "cache_control" in static and "cache_control" not in context
    return context["text"]


async def test_a_gated_turn_changes_only_tool_choice_between_iterations(loop, run, session):
    for text, tool, tool_input, call_count in loop.gated_turns:
        responses = [
            tool_use_message(tool, tool_input),
            *[text_message("答好了。")] * (call_count - 1),
        ]
        first, *rest = await run(text, responses, session=session)
        assert len(rest) == call_count - 1
        assert first["tool_choice"] == {"type": "tool", "name": tool}
        assert rest[0]["tool_choice"] == {"type": "auto"}
        assert all(_cached_bytes(call) == _cached_bytes(first) for call in rest), text
        assert _context_block(first).startswith(loop.dynamic_heading)


async def test_an_ungated_turn_runs_auto_from_the_first_iteration(loop, run, session):
    (only,) = await run(loop.ungated_turn, [text_message("给你。")], session=session)
    assert only["tool_choice"] == {"type": "auto"}


async def test_thinking_follows_the_configured_effort(loop, run, session):
    (default,) = await run(loop.ungated_turn, [text_message("给你。")], session=session)
    assert default["thinking"] == {"type": "adaptive"}
    assert default["output_config"] == {"effort": "low"}
    (off,) = await run(
        loop.ungated_turn, [text_message("给你。")], session=session, thinking_effort=None
    )
    assert off["thinking"] == {"type": "disabled"} and "output_config" not in off


async def test_local_time_renders_only_from_the_sessions_own_clock(run, session):
    (bare,) = await run("你好", [text_message("你好")], session=session)
    assert "local_time" not in _context_block(bare)

    zoned = session.model_validate(session.model_dump() | {"timezone": "Europe/Lisbon"})
    (call,) = await run("你好", [text_message("你好")], session=zoned)
    offset = datetime.now(ZoneInfo("Europe/Lisbon")).strftime("%z")
    assert f"{offset[:3]}:{offset[3:]}" in _context_block(call)

    fixed = datetime(2026, 5, 30, 10, 0, tzinfo=ZoneInfo("Europe/Lisbon"))
    pinned = session.model_validate(
        session.model_dump() | {"timezone": "America/New_York", "now": fixed}
    )
    (call,) = await run("你好", [text_message("你好")], session=pinned)
    assert "2026-05-30T10:00" in _context_block(call)


def test_clock_context_prefers_an_explicit_now_and_rejects_unknown_zones():
    assert ClockContext().local_now() is None
    assert ClockContext(timezone="Europe/Lisbon").local_now().tzinfo == ZoneInfo("Europe/Lisbon")
    fixed = datetime(2026, 5, 30, 10, 0, tzinfo=ZoneInfo("Europe/Lisbon"))
    assert ClockContext(timezone="America/New_York", now=fixed).local_now() is fixed
    with pytest.raises(ValidationError):
        ClockContext(timezone="Mars/Olympus_Mons")
