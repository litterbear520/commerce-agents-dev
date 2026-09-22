"""一条事实是怎么进来的：校验、写入过滤器、提取、tier-one 选取。"""
# 项目中对应 commerce-common/tests/test_memory_facts.py
# 项目里还有 test_extraction_template_continuations_keep_their_joining_space，
# 检查英文模板续行反斜杠前留了拼接用的空格；中文模板词间不加空格，这里省略。
# _normalize 折叠大小写、_same_fact 按空格切词算 Jaccard，都是针对英文的算法，
# 所以覆盖这两个函数的用例保留英文语料，其余用例用中文。

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from commerce_common.fencing import Fence
from commerce_common.memory import (
    DEFAULT_BLOCKED_PATTERNS,
    MEMORY_EXTRACTION_TEMPLATE,
    MEMORY_WRITE_REJECTED_TEXT,
    InMemoryMemoryStore,
    JsonFileMemoryStore,
    MemoryWriteFilter,
    MemoryWriteRejected,
    extract_and_store,
    extract_facts,
    select_tier_one_facts,
    validate_fact,
    write_filter_for,
)
from commerce_common.testing import extraction_client
from commerce_common.turn import session_tag
from commerce_common.types import MemoryCategory, MemoryFact

FENCE = Fence(label="test_data", notice="数据。")
DEFAULT_FILTER = write_filter_for()
PROPOSAL = {"key": "sleep", "value": "同住的人睡觉怕热", "category": "constraint"}


def fact(
    key: str, value: str, category: str | None = None, *, write_filter=DEFAULT_FILTER
) -> MemoryFact:
    return validate_fact(key, value, category, fence=FENCE, write_filter=write_filter)


async def extract(client, existing=(), *, write_filter=DEFAULT_FILTER):
    return await extract_facts(
        client,
        "m",
        "用户：海边什么地方都行，1500 以内",
        list(existing),
        extraction_prompt="角色的提示词",
        fence=FENCE,
        write_filter=write_filter,
    )


async def extract_into(store, client, session_id=None):
    return await extract_and_store(
        store,
        "u-1",
        client,
        "m",
        "用户：你好",
        extraction_prompt="p",
        fence=FENCE,
        write_filter=DEFAULT_FILTER,
        source_session_id=session_id,
    )


# ── validate_fact 与写入过滤器 ────────────────────────────────────────


def test_validate_fact_normalizes_the_key_and_clamps_to_the_schema_caps():
    assert fact("Camping Style", "喜欢轻量装备").key == "camping_style"
    clamped = fact("k", "x" * 250)
    assert len(clamped.value) <= 200 and clamped.value.endswith("...[truncated]")
    assert len(fact("K " * 100, "v").key) <= 64


@pytest.mark.parametrize(
    "value",
    [
        "完整卡号：4000 1234 5678 9010",
        "卡号 4000.1234.5678.9010",
        "身份证号 123-45-6789",
        "配送的事打这个电话 010 555 0100",
        "六点以后打 (010) 555-0100",
        "会员账号 001122334455",
        "扣款账户 ZZ12ACME00001234567890",
        "联系邮箱 avery@example.test",
    ],
)
def test_the_default_filter_rejects_identifiers_without_repeating_them(value):
    with pytest.raises(MemoryWriteRejected) as rejected:
        fact("note", value)
    assert str(rejected.value) == MEMORY_WRITE_REJECTED_TEXT and value.split()[-1] not in str(
        rejected.value
    )
    assert issubclass(MemoryWriteRejected, ValueError)  # 宽松的调用方可以直接跳过这条事实


def test_the_filter_reads_the_key_as_well():
    with pytest.raises(MemoryWriteRejected):
        fact("card 4000123456789010", "就选这张")


@pytest.mark.parametrize(
    "value",
    [
        "家庭办公这套的预算大概 1800 全包",
        "穿 EU 42、US 9 码",
        "行程是 2026-09-12 到 2026-09-19",
        "订单号通常长这样 ORD-2026-0817",
    ],
)
def test_the_default_filter_keeps_ordinary_facts(value):
    assert fact("note", value).value == value


def test_deployment_patterns_add_to_the_defaults_and_none_disables_the_filter():
    strict = MemoryWriteFilter.build([r"(?i)过敏"])
    with pytest.raises(MemoryWriteRejected):
        fact("wool", "对羊毛过敏", write_filter=strict)
    with pytest.raises(MemoryWriteRejected):
        fact("card", "4000123456789010", write_filter=strict)
    assert fact("wool", "对羊毛过敏").value
    assert fact("card", "4000123456789010", write_filter=None).value
    assert write_filter_for(("x",)) is write_filter_for(("x",))
    assert len(write_filter_for(("x", "y")).patterns) == len(DEFAULT_BLOCKED_PATTERNS) + 2


def test_host_checks_run_on_the_normalized_fact_after_the_patterns():
    seen: list[tuple[str, str]] = []

    def detector(key: str, value: str) -> bool:
        seen.append((key, value))
        return "雇主" in value

    strict = MemoryWriteFilter.build(checks=[detector])
    assert fact("Coffee Setup", "只买整豆", write_filter=strict).key == "coffee_setup"
    assert seen == [("coffee_setup", "只买整豆")]
    with pytest.raises(MemoryWriteRejected):
        fact("job", "给一家点名道姓的雇主打工", write_filter=strict)
    seen.clear()
    with pytest.raises(MemoryWriteRejected):
        fact("card", "4000123456789010", write_filter=strict)
    assert seen == []  # 正则命中就不会走到 checks


# ── 提取 ──────────────────────────────────────────────────────────────


async def test_extraction_sends_the_prompt_and_transcript_and_keeps_the_valid_proposals():
    proposals = [
        {"key": "parents_trip", "value": "海边出行，1500 以内", "category": "context"},
        {"key": "payment_card", "value": "4000 1234 5678 9010", "category": "context"},
        {"key": "wool", "value": "对羊毛过敏", "category": "constraint"},
    ]
    client = extraction_client(proposals)
    assert [f.key for f in await extract(client)] == ["parents_trip", "wool"]
    (call,) = client.calls
    assert call["system"] == "角色的提示词" and "海边什么地方都行" in call["messages"][0]["content"]
    stricter = await extract(client, write_filter=MemoryWriteFilter.build([r"(?i)过敏"]))
    assert [f.key for f in stricter] == ["parents_trip"]


async def test_extraction_drops_restatements_of_held_or_earlier_proposals():
    # 英文语料：这里要覆盖 _same_fact 的词集重叠分支。
    proposals = [
        {"key": "bedroom", "value": "the bedroom has no outdoor space", "category": "context"},
        {"key": "room", "value": "bedroom has no outdoor space at all", "category": "context"},
        {"key": "size", "value": "wears EU 42", "category": "context"},
        {"key": "shoes", "value": "Wears EU 42", "category": "context"},
    ]
    facts = await extract(extraction_client(proposals), [fact("size_known", "wears eu 42")])
    assert [f.key for f in facts] == ["bedroom"]


async def test_extraction_keeps_an_update_under_a_held_key_but_not_a_restatement():
    # 英文语料：末尾一段靠 _normalize 折叠大小写来判定"值没变"。
    held = [fact("budget_ceiling", "wants to stay under $120 all-in per ticket")]
    proposals = [
        {"key": "budget_ceiling", "value": "wants to stay under $140 all-in per ticket"},
        {"key": "budget", "value": "wants to stay under $140 all-in per ticket"},
    ]
    facts = await extract(extraction_client(proposals), held)
    assert [(f.key, f.value) for f in facts] == [
        ("budget_ceiling", "wants to stay under $140 all-in per ticket")
    ]
    unchanged = [{"key": "budget_ceiling", "value": "Wants to stay under $120 all-in per ticket"}]
    assert await extract(extraction_client(unchanged), held) == []


@pytest.fixture(params=["memory", "file"])
def store(request, tmp_path):
    return (
        InMemoryMemoryStore()
        if request.param == "memory"
        else JsonFileMemoryStore(tmp_path / "memory.json")
    )


async def test_extract_and_store_writes_unless_the_subject_was_purged_meanwhile(store):
    assert [f.key for f in await extract_into(store, extraction_client([PROPOSAL]))] == ["sleep"]
    await store.clear("u-1")

    gate = asyncio.Event()
    client = extraction_client([PROPOSAL], before_call=lambda _: gate.wait())
    extraction = asyncio.create_task(extract_into(store, client))
    await asyncio.sleep(0)  # 提取已经读过 store，正卡在模型调用上
    assert len(client.calls) == 1
    await store.clear("u-1")
    gate.set()
    assert await extraction == [] and await store.get_facts("u-1") == []


async def test_extracted_facts_carry_the_writing_sessions_tag_not_its_id(store):
    (written,) = await extract_into(store, extraction_client([PROPOSAL]), "sess-credential")
    assert written.source_session_id == session_tag("sess-credential")
    (stored,) = await store.get_facts("u-1")
    assert stored.source_session_id == written.source_session_id != "sess-credential"


async def test_a_purge_of_another_subject_does_not_block_the_write(store):
    gate = asyncio.Event()
    client = extraction_client([PROPOSAL], before_call=lambda _: gate.wait())
    extraction = asyncio.create_task(extract_into(store, client))
    await asyncio.sleep(0)
    await store.clear("u-2")
    gate.set()
    assert [f.key for f in await extraction] == ["sleep"]


def test_extraction_template_tells_the_extractor_to_record_only_what_was_said():
    for phrase in (
        "只包含{speaker}说过的话",
        "需要推断才能得到的",
        "已存事实和新说法",
    ):
        assert phrase in MEMORY_EXTRACTION_TEMPLATE


# ── tier one ──────────────────────────────────────────────────────────


def dated(key: str, category: str = "preference", days_ago: int = 0) -> MemoryFact:
    return MemoryFact(
        key=key,
        value=f"{key} 的值",
        category=MemoryCategory(category),
        updated_at=datetime(2026, 6, 1, tzinfo=UTC) - timedelta(days=days_ago),
    )


def test_tier_one_keeps_every_constraint_and_fills_the_cap_with_the_most_recent_rest():
    facts = [
        dated("no_outdoor_space", "constraint", days_ago=400),
        *(dated(f"pref_{i}", days_ago=i) for i in range(9)),
    ]
    assert [f.key for f in select_tier_one_facts(facts, cap=8)] == [
        "no_outdoor_space",
        *(f"pref_{i}" for i in range(7)),
    ]
    undated = MemoryFact(key="undated", value="没有时间戳", category=MemoryCategory.PREFERENCE)
    assert select_tier_one_facts([undated], cap=8) == [undated]
    assert select_tier_one_facts([], cap=8) == []
