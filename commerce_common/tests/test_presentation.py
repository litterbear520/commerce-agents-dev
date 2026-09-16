"""展示层框架测试：建议按钮验证、run_presentation 管线、拒绝映射。"""

import pytest
from pydantic import BaseModel, ValidationError

from commerce_common.presentation import (
    EnrichmentContext,
    PresentationComponent,
    PresentationRefused,
    PresentSuggestionsPayload,
    run_presentation,
)


class _Payload(BaseModel):
    ident: str
    suggestions: list[str] = []


def _context() -> EnrichmentContext:
    return EnrichmentContext(backend=None, config=None, session=None, state={"known": 1})


def test_suggestions_payload_sanitizes_and_rejects_a_list_that_sanitizes_away():
    payload = PresentSuggestionsPayload.model_validate(
        {"suggestions": ["y" * 200, "加入\u200b购物车\x07", "\u200b\ufeff", "对比一下"]}
    )
    assert payload.suggestions == ["y" * 79 + "…", "加入购物车", "对比一下"]
    with pytest.raises(ValidationError):
        PresentSuggestionsPayload.model_validate({"suggestions": ["a", "b", "c", "d", "e"]})
    with pytest.raises(ValidationError, match="清洗后所有建议都为空"):
        PresentSuggestionsPayload.model_validate({"suggestions": ["\u200b\ufeff", "\x00\x01 "]})


async def test_component_without_a_hook_renders_the_payload_as_sent():
    spec = PresentationComponent(name="present_x", component="x", payload_model=_Payload)
    outcome = await run_presentation(spec, {"ident": "a"}, _context(), "已展示。")
    assert outcome.result_text == "已展示。"
    (event,) = outcome.events
    assert event.type == "ui" and event.data == {
        "component": "x",
        "payload": {"ident": "a", "suggestions": []},
    }


async def test_invalid_payload_is_an_error_naming_the_tool():
    spec = PresentationComponent(name="present_x", component="x", payload_model=_Payload)
    outcome = await run_presentation(spec, {}, _context(), "已展示。")
    assert outcome.is_error and outcome.result_text.startswith("present_x 参数无效：")
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
    assert outcome.events[0].data == {"component": "x", "payload": {"ident": "a", "rows": [1, 2]}}


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
