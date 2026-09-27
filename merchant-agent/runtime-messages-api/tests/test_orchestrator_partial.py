"""商户编排器的 ui_partial 帧：卡片流式输出时，只渲染会话来源记录能解析出来的部分。"""
# 项目中对应 merchant-agent/runtime-messages-api/tests/test_orchestrator_partial.py
# 省略：变更预览先渲染暂存记录再渲染标题的用例（Step 20）

from __future__ import annotations

import json

import pytest

from commerce_common.testing import FakeClient, text_message, tool_calls_message
from merchant_agent import BusinessSnapshot, Listing
from merchant_agent_runtime import MerchantAgent


@pytest.fixture
def make_agent(backend, skills):
    def _make(responses, chunks: dict[int, list[str]] | None = None) -> MerchantAgent:
        return MerchantAgent(backend=backend, skills=skills, client=FakeClient(responses, chunks))

    return _make


async def collect_events(agent: MerchantAgent, text: str, session, state) -> list:
    messages = [{"role": "user", "content": text}]
    return [event async for event in agent.stream_turn(messages, session, state)]


def chunked(payload: dict, *cuts: str) -> list[str]:
    """``payload`` 转成 JSON，按 ``cuts`` 依次在每个片段之后切开。"""
    text, pieces = json.dumps(payload), []
    for cut in cuts:
        index = text.index(cut) + len(cut)
        pieces.append(text[:index])
        text = text[index:]
    return [*pieces, text]


DIGEST = {
    "title": "今天早上",
    "items": [
        {"kind": "low_stock", "ref_id": "L-202", "headline": "只剩 2 件，一个月卖 41 件"},
        {"kind": "slow_mover", "ref_id": "L-203", "headline": "库存 120 件，一个月只卖 4 件"},
    ],
}
CHIPS = ("present_suggestions", {"suggestions": ["给 L-202 补货 40 件"]})


async def test_a_digest_streams_entry_by_entry_with_listing_joins(make_agent, session, state):
    state.remember_listings(
        [Listing(listing_id="L-202", title="Sprout 陶瓷花盆，6 英寸", price=18.0)]
    )
    # json.dumps 会把汉字转义成 \uXXXX，所以切点只用 ASCII 片段
    chunks = {0: chunked(DIGEST, '"headline": "', '"}')}
    agent = make_agent([tool_calls_message(("present_digest", DIGEST), CHIPS)], chunks)
    events = await collect_events(agent, "给我今天的晨报", session, state)
    partials = [e for e in events if e.type == "ui_partial"]
    assert [len(p.data["payload"]["items"]) for p in partials] == [0, 1, 2]
    assert partials[0].data["payload"]["title"] == "今天早上"
    assert partials[1].data["payload"]["items"][0]["listing"]["listing_id"] == "L-202"
    ui, chips = [e for e in events if e.type == "ui"]
    assert ui.data["stream_id"] == partials[0].data["stream_id"] == "tu-1"
    assert chips.data["component"] == "suggestions"
    assert len(agent.client.calls) == 1  # 同一轮带了建议按钮，轮次就此结束


async def test_a_digest_entry_with_a_kind_the_schema_lacks_waits_for_validation(
    make_agent, session, state
):
    payload = {"title": "今天", "items": [{"kind": "weather", "headline": "晚点下雨"}]}
    chunks = {0: chunked(payload, '"}')}
    agent = make_agent(
        [tool_calls_message(("present_digest", payload), CHIPS), text_message("改好了。")], chunks
    )
    events = await collect_events(agent, "简单说说今天", session, state)
    partials = [e for e in events if e.type == "ui_partial"]
    assert [p.data["payload"]["items"] for p in partials] == [[]]
    (rejected,) = [
        e for e in events if e.type == "tool_result" and e.data["tool"] == "present_digest"
    ]
    assert rejected.data["is_error"]


async def test_a_metrics_card_waits_for_its_first_grounded_pick(make_agent, session, state):
    state.remember_snapshot(
        BusinessSnapshot(
            period="2026-06-19/2026-06-25",
            compare_to="2026-06-12/2026-06-18",
            sales=18432.0,
            orders=412,
            traffic=9120,
            conversion_rate=4.5,
            average_order_value=44.7,
        )
    )
    payload = {
        "title": "上周",
        "picks": [{"metric": "footfall"}, {"metric": "sales", "note": "比前一周高"}],
    }
    chunks = {0: chunked(payload, '"footfall"}', '"sales"')}
    agent = make_agent(
        [
            tool_calls_message(("present_metrics", payload), CHIPS),
            text_message("客流没有统计。"),
        ],
        chunks,
    )
    events = await collect_events(agent, "帮我回顾一下上周", session, state)
    partials = [e for e in events if e.type == "ui_partial"]
    # 只有标题不出帧，没有依据的指标也不出；有依据的那个出帧。
    assert [[m["metric"] for m in p.data["payload"]["metrics"]] for p in partials] == [["sales"]]
    first = partials[0].data["payload"]
    assert first["period"] == "2026-06-19/2026-06-25"
    assert "note" not in first["metrics"][0] or first["metrics"][0]["note"] is None
    # 被跳过的指标附了一条说明，轮次留给下一轮收尾。
    assert len(agent.client.calls) == 2
