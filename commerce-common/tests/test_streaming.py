# 项目中对应 commerce-common/tests/test_streaming.py
# AgentEvent 构造、SSE 序列化、parse_partial_json 流式补全

import json

from commerce_common.streaming import AgentEvent, parse_partial_json, to_sse

# ── SSE 序列化 ──────────────────────────────────────────────


def test_sse_serialization_roundtrip():
    event = AgentEvent.ui("products", {"items": [{"product": {"product_id": "p-1"}}]})
    frame = to_sse(event)
    assert frame.startswith("event: ui\n")
    assert frame.endswith("\n\n")
    data_line = frame.split("\n")[1]
    payload = json.loads(data_line.removeprefix("data: "))
    assert payload["component"] == "products"


def test_event_constructors_carry_expected_fields():
    assert AgentEvent.text_delta("hi").data == {"text": "hi"}
    err = AgentEvent.error("nope")
    assert err.type == "error"
    done = AgentEvent.turn_complete("end_turn", {"input_tokens": 10, "output_tokens": 2}, 480, 0)
    assert done.data["usage"]["input_tokens"] == 10 and done.data["elapsed_ms"] == 480
    assert done.data["results_cleared"] == 0


# ── progress 事件 ────────────────────────────────────────────


def test_progress_message_only_omits_optional_keys():
    event = AgentEvent.progress("querying metrics")
    assert event.type == "progress"
    assert event.data == {"message": "querying metrics"}


def test_progress_full_form_carries_tool_and_step():
    event = AgentEvent.progress("step 2", tool="run_analysis", step=2)
    assert event.data == {"message": "step 2", "tool": "run_analysis", "step": 2}


def test_progress_step_zero_is_carried():
    event = AgentEvent.progress("starting", tool="run_analysis", step=0)
    assert event.data["step"] == 0


def test_progress_sse_roundtrip():
    frame = to_sse(AgentEvent.progress("scanning listings", tool="run_analysis"))
    assert frame.startswith("event: progress\n")
    assert frame.endswith("\n\n")
    payload = json.loads(frame.split("\n")[1].removeprefix("data: "))
    assert payload == {"message": "scanning listings", "tool": "run_analysis"}


# ── parse_partial_json ──────────────────────────────────────


def test_parse_partial_json_complete_object_passes_through():
    assert parse_partial_json('{"title": "Picks", "picks": []}') == {
        "title": "Picks",
        "picks": [],
    }


def test_parse_partial_json_leaves_out_a_string_cut_mid_value_with_its_key():
    # 写到一半的字符串连同 key 一起删掉
    assert parse_partial_json('{"title": "Best te') == {}
    assert parse_partial_json('{"a": "done", "b": "op') == {"a": "done"}
    # 数组里未闭合的元素也删掉，已闭合的保留
    assert parse_partial_json('{"pros": ["light", "chea') == {"pros": ["light"]}
    # settle_strings=False 时就地闭合，文本随流式输出逐渐变长
    assert parse_partial_json('{"title": "Best te', settle_strings=False) == {"title": "Best te"}


def test_parse_partial_json_waits_on_string_cut_mid_key():
    # key 写到一半，整个字段还没开始，返回 None 或只保留之前的
    assert not parse_partial_json('{"tit')
    assert parse_partial_json('{"title"') is None
    assert parse_partial_json('{"title": "x", "pic') == {"title": "x"}


def test_parse_partial_json_trims_trailing_comma():
    assert parse_partial_json('{"a": 1,') == {"a": 1}
    assert parse_partial_json('{"picks": [{"product_id": "p-1"},') == {
        "picks": [{"product_id": "p-1"}]
    }


def test_parse_partial_json_waits_on_trailing_colon():
    # 冒号后面还没有值，等不到就返回 None
    assert parse_partial_json('{"a": 1, "b":') is None
    assert parse_partial_json('{"a": 1, "b": ') is None


def test_parse_partial_json_respects_escaped_quotes():
    parsed = parse_partial_json('{"quote": "she said \\"hi', settle_strings=False)
    assert parsed == {"quote": 'she said "hi'}
    parsed = parse_partial_json('{"quote": "she said \\"hi\\"", "next": "and th')
    assert parsed == {"quote": 'she said "hi"'}


def test_parse_partial_json_closes_nested_structures():
    prefix = '{"picks": [{"product_id": "p-1"}, {"product_id": "p-2'
    # 半截 ID 不渲染，它的槽位以空对象出现，等 ID 写完才填入
    assert parse_partial_json(prefix) == {"picks": [{"product_id": "p-1"}, {}]}
    assert "product_id" not in parse_partial_json('{"picks": [{"product_id": "p-1')["picks"][0]
    assert parse_partial_json(prefix, settle_strings=False) == {
        "picks": [{"product_id": "p-1"}, {"product_id": "p-2"}]
    }


def test_parse_partial_json_rejects_non_object_prefixes():
    # 只处理对象，数组、字符串、纯文本、空串全返回 None
    assert parse_partial_json("[1, 2") is None
    assert parse_partial_json('"just a string') is None
    assert parse_partial_json("plain text") is None
    assert parse_partial_json("") is None
