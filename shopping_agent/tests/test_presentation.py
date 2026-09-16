"""展示层测试：payload 验证、补全钩子、拒绝映射、价差计算。"""

import pytest
from pydantic import BaseModel, ValidationError

from commerce_common.presentation import (
    EnrichmentContext,
    PresentationComponent,
    PresentationRefused,
    PresentSuggestionsPayload,
    run_presentation,
)
from shopping_agent.enrichment import comparison_price_delta
from shopping_agent.tools.presentation import PresentProductsPayload

# ── 辅助 ────────────────────────────────────────────────────────────


class _Payload(BaseModel):
    ident: str


def _context() -> EnrichmentContext:
    return EnrichmentContext(backend=None, config=None, session=None, state=None)


def _entry(product_id: str, price: float | None) -> dict:
    # 模拟补全后的对比条目
    product: dict = {"product_id": product_id, "title": product_id}
    if price is not None:
        product["price"] = price
    return {"product_id": product_id, "product": product}


# ── 建议按钮验证 ────────────────────────────────────────────────────


def test_suggestions_payload_sanitizes_and_rejects_a_list_that_sanitizes_away():
    # 清洗：超长截断、零宽字符和控制符去掉、空串丢掉
    payload = PresentSuggestionsPayload.model_validate(
        {"suggestions": ["y" * 200, "加入​购物车\x07", "​﻿", "对比一下"]}
    )
    assert payload.suggestions == ["y" * 79 + "…", "加入购物车", "对比一下"]
    # 超过 4 条拒绝
    with pytest.raises(ValidationError):
        PresentSuggestionsPayload.model_validate({"suggestions": ["a", "b", "c", "d", "e"]})
    # 全部清洗为空时拒绝
    with pytest.raises(ValidationError, match="清洗后所有建议都为空"):
        PresentSuggestionsPayload.model_validate({"suggestions": ["​﻿", "\x00\x01 "]})


# ── payload 多余字段丢弃 ────────────────────────────────────────────


def test_product_picks_carry_no_model_authored_label():
    payload = PresentProductsPayload.model_validate(
        {"picks": [{"product_id": "a", "reason": "便宜", "highlight": "推荐"}]}
    )
    assert payload.picks[0].model_dump(exclude_none=True) == {
        "product_id": "a",
        "reason": "便宜",
    }


# ── run_presentation 管线 ──────────────────────────────────────────


async def test_component_without_a_hook_renders_the_payload_as_sent():
    spec = PresentationComponent(name="present_x", component="x", payload_model=_Payload)
    outcome = await run_presentation(spec, {"ident": "a"}, _context(), "已展示。")
    assert outcome.result_text == "已展示。"
    (event,) = outcome.events
    assert event.type == "ui"
    assert event.data == {"component": "x", "payload": {"ident": "a"}}


async def test_invalid_payload_is_an_error_naming_the_tool():
    spec = PresentationComponent(name="present_x", component="x", payload_model=_Payload)
    outcome = await run_presentation(spec, {}, _context(), "已展示。")
    assert outcome.is_error
    assert outcome.result_text.startswith("present_x 参数无效：")
    assert outcome.events == []


async def test_hook_notes_join_the_result_text_and_the_payload_renders_as_enriched():
    async def enrich(payload: _Payload, context: EnrichmentContext) -> dict:
        context.notes.append("跳过了 b。")
        return {"ident": payload.ident, "rows": [1, 2]}

    spec = PresentationComponent(
        name="present_x", component="x", payload_model=_Payload, enrich=enrich
    )
    outcome = await run_presentation(spec, {"ident": "a"}, _context(), "已展示。")
    assert outcome.result_text == "已展示。 跳过了 b。"
    assert outcome.events[0].data == {
        "component": "x",
        "payload": {"ident": "a", "rows": [1, 2]},
    }


# ── 拒绝映射 ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raised", "is_error", "blocked"),
    [
        (PresentationRefused("没有 id", "provenance"), False, "provenance"),
        (PresentationRefused("找不到记录"), True, None),
        (ValueError("钩子拒绝"), True, None),
    ],
)
async def test_hook_refusals_map_onto_held_or_error(raised, is_error, blocked):
    async def enrich(payload: _Payload, context: EnrichmentContext) -> dict:
        raise raised

    spec = PresentationComponent(
        name="present_x", component="x", payload_model=_Payload, enrich=enrich
    )
    outcome = await run_presentation(spec, {"ident": "a"}, _context(), "已展示。")
    assert outcome.result_text == str(raised)
    assert (outcome.is_error, outcome.blocked) == (is_error, blocked)
    assert outcome.events == []


# ── price_delta 计算 ────────────────────────────────────────────────


def test_price_delta_spans_cheapest_to_priciest():
    delta = comparison_price_delta([_entry("a", 27.0), _entry("b", 34.0), _entry("c", 29.5)])
    assert delta == {
        "amount": 7.0,
        "low_product_id": "a",
        "low_price": 27.0,
        "high_product_id": "b",
        "high_price": 34.0,
    }


def test_price_delta_none_when_prices_equal():
    assert comparison_price_delta([_entry("a", 30.0), _entry("b", 30.0)]) is None


def test_price_delta_needs_two_priced_entries():
    assert comparison_price_delta([_entry("a", 30.0)]) is None
    assert comparison_price_delta([_entry("a", 30.0), _entry("b", None)]) is None


def test_price_delta_none_across_currencies():
    eur = _entry("b", 30.0)
    eur["product"]["currency"] = "EUR"
    assert comparison_price_delta([_entry("a", 34.0), eur]) is None
