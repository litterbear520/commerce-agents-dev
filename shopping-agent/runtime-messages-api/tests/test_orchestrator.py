"""编排器的 ui_partial 帧和预取测试。"""
# 项目中对应 shopping-agent/runtime-messages-api/tests/test_orchestrator.py

from __future__ import annotations

from commerce_common.testing import text_message, tool_calls_message, tool_use_message
from shopping_agent import Product
from shopping_agent_runtime.orchestrator import ShoppingAgent


async def collect_events(agent: ShoppingAgent, text: str, session, state) -> list:
    messages = [{"role": "user", "content": text}]
    return [event async for event in agent.stream_turn(messages, session, state)]


PRODUCTS = [
    Product(product_id="p-100", title="2-Person Backpacking Tent", price=149.0),
    Product(product_id="p-200", title="Two-Burner Camp Stove", price=64.5),
]

FINAL_INPUT = {
    "title": "A few options",
    "picks": [
        {"product_id": "p-100", "reason": "lightweight"},
        {"product_id": "p-200", "reason": "cheap"},
    ],
}

# 四段 delta；只有三段改变了用户能看到的内容。第 3 段补全了第 2 段已经
# 显示的 reason 字符串，结构没变，不能重新发帧。
CHUNKS = {
    0: [
        '{"title": "A few options", "picks": [{"product_id": "p-10',  # 标题出现，还没有可解析的条目
        '0", "reason": "light',  # p-100 解析出来：第一个条目出现
        'weight"}',  # reason 文本变长：结构没变
        ', {"product_id": "p-200", "reason": "cheap"}]}',  # 第二个条目出现
    ]
}


async def test_ui_partial_emitted_on_structural_change_only(make_agent, session, state):
    state.remember_products(PRODUCTS)
    agent = make_agent(
        [tool_use_message("present_products", FINAL_INPUT), text_message("Here you go.")],
        chunks=CHUNKS,
    )
    events = await collect_events(agent, "show me camping picks", session, state)

    partials = [e for e in events if e.type == "ui_partial"]
    assert len(partials) == 3
    assert [len(p.data["payload"]["items"]) for p in partials] == [0, 1, 2]
    assert all(p.data["component"] == "products" for p in partials)
    # 每帧都带 stream_id，前端用它替换上一帧。
    assert {p.data["stream_id"] for p in partials} == {"tu-1"}

    (ui,) = [e for e in events if e.type == "ui"]
    assert ui.data["stream_id"] == "tu-1"
    assert len(ui.data["payload"]["items"]) == 2


async def test_ui_partial_skips_unresolvable_ids(make_agent, session, state):
    # 没有溯源记录时什么都解析不出来，只有标题帧的结构不同。
    agent = make_agent(
        [tool_use_message("present_products", FINAL_INPUT), text_message("...")],
        chunks=CHUNKS,
    )
    events = await collect_events(agent, "show me camping picks", session, state)
    partials = [e for e in events if e.type == "ui_partial"]
    assert len(partials) == 1
    assert partials[0].data["payload"]["items"] == []


async def test_no_frame_goes_out_before_a_title_or_an_item(make_agent, session, state):
    state.remember_products(PRODUCTS)
    untitled = {0: [CHUNKS[0][0].replace('"title": "A few options", ', ""), *CHUNKS[0][1:]]}
    final = {key: value for key, value in FINAL_INPUT.items() if key != "title"}
    agent = make_agent(
        [tool_use_message("present_products", final), text_message("Here you go.")],
        chunks=untitled,
    )
    events = await collect_events(agent, "show me camping picks", session, state)
    partials = [e for e in events if e.type == "ui_partial"]
    assert [len(p.data["payload"]["items"]) for p in partials] == [1, 2]
    # 半截 reason 不渲染：第一个条目到达时没有 reason。
    assert "reason" not in partials[0].data["payload"]["items"][0]


GUIDE_INPUT = {
    "title": "Pitching on rocky ground",
    "sections": [
        {"heading": "Pick the spot", "body": "Look for a flat patch clear of roots."},
        {"heading": "Anchor it", "body": "Use rock stacks where stakes will not go in."},
    ],
}

GUIDE_CHUNKS = {
    0: [
        '{"title": "Pitching on rocky ground", "sections": [{"heading": "Pick the sp',
        'ot", "body": "Look for a flat patch clear of roots."}, {"heading": "Anchor',
        ' it", "body": "Use rock stacks where stakes will not go in."}]}',
    ]
}


async def test_a_guide_streams_its_title_then_each_closed_section(make_agent, session, state):
    chips = ("present_suggestions", {"suggestions": ["Show freestanding tents"]})
    agent = make_agent(
        [tool_calls_message(("present_guide", GUIDE_INPUT), chips)], chunks=GUIDE_CHUNKS
    )
    events = await collect_events(agent, "how do I pitch a tent on rock", session, state)
    partials = [e for e in events if e.type == "ui_partial"]
    assert [len(p.data["payload"]["sections"]) for p in partials] == [0, 1, 2]
    assert partials[0].data["payload"]["title"] == "Pitching on rocky ground"
    assert all(p.data["component"] == "guide" for p in partials)
    guide, suggestions = [e for e in events if e.type == "ui"]
    assert "suggestions" not in guide.data["payload"]
    assert suggestions.data["payload"]["suggestions"] == ["Show freestanding tents"]
    # 建议按钮在展示组件的同一轮发出，关闭了轮次：只调用了一次模型。
    assert len(agent.client.calls) == 1


# ── 预取 ──────────────────────────────────────────────────────────────


async def test_prefetch_returns_preferences_and_cart(backend, skills, session):
    agent = ShoppingAgent(backend=backend, skills=skills, client=object())
    preferences, cart = await agent._prefetch(session)
    assert preferences is not None and preferences.display_name == "Priya"
    assert cart is not None


async def test_prefetch_tolerates_failure(backend, skills, session, monkeypatch):
    async def broken_preferences(session):
        raise RuntimeError("profile service down")

    monkeypatch.setattr(backend, "get_preferences", broken_preferences)
    agent = ShoppingAgent(backend=backend, skills=skills, client=object())
    preferences, cart = await agent._prefetch(session)
    assert preferences is None
    assert cart is not None


# ── 中断修复 ──────────────────────────────────────────────────────────


async def test_a_turn_closed_mid_round_leaves_no_unpaired_tool_use(make_agent, session, state):
    """调用方可能在任何事件处停止读取；存储的对话必须仍能用于下一次请求。"""
    agent = make_agent([tool_use_message("search_products", {"query": "tent"}), text_message("x")])
    messages = [{"role": "user", "content": "find me a tent"}]
    stream = agent.stream_turn(messages, session, state)
    async for event in stream:
        if event.type == "tool_call":
            break
    await stream.aclose()
    tool_uses = [
        block
        for message in messages
        if message["role"] == "assistant"
        for block in message["content"]
        if (block.get("type") if isinstance(block, dict) else block.type) == "tool_use"
    ]
    results = [
        block
        for message in messages
        if message["role"] == "user" and isinstance(message["content"], list)
        for block in message["content"]
        if block.get("type") == "tool_result"
    ]
    assert len(results) == len(tool_uses)
    assert messages[-1]["role"] == "user"


async def test_a_call_that_finished_before_the_close_keeps_its_real_result(
    make_agent, session, state
):
    """在 tool_result 事件处关闭：搜索已经执行完毕，所以记录的是真实结果
    而不是让模型重新调用的邀请。"""
    agent = make_agent([tool_use_message("search_products", {"query": "tent"}), text_message("x")])
    messages = [{"role": "user", "content": "find me a tent"}]
    stream = agent.stream_turn(messages, session, state)
    async for event in stream:
        if event.type == "tool_result":
            break
    await stream.aclose()
    result = messages[-1]["content"][0]
    assert result["type"] == "tool_result" and not result["is_error"]
    assert "interrupted" not in result["content"]
