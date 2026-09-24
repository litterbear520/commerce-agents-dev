# 项目中对应 merchant-agent/core/tests/test_executor.py
# 省略：暂存写入、审批、丢弃、参数强转（Step 20）；展示工具（Step 19）；
# 分析委托（Step 21）；以及这些流程里用到读取的那部分断言

import pytest

from merchant_agent import InventoryAlert
from merchant_agent.executor import MerchantToolExecutor
from merchant_agent.fencing import MERCHANT_FENCE
from merchant_agent.serialization import SEARCH_EMPTY_HEADER


@pytest.fixture
def executor(backend, config, skills, session, state) -> MerchantToolExecutor:
    return MerchantToolExecutor(
        backend=backend, config=config, skills=skills, session=session, state=state
    )


# ── 读取 ─────────────────────────────────────────────────────────────


async def test_snapshot_is_fenced_and_remembered(executor, state):
    result = await executor.execute("get_business_snapshot", {})
    assert not result.is_error
    assert result.result_text.startswith(MERCHANT_FENCE.open)
    assert result.result_text.rstrip().endswith(MERCHANT_FENCE.close)
    assert state.latest_snapshot is not None


async def test_search_listings_records_provenance(executor, state):
    result = await executor.execute("search_listings", {"query": "花盆"})
    assert not result.is_error
    header, _, fenced = result.result_text.partition("\n")
    assert header.startswith("搜索返回 ")
    assert fenced.startswith(MERCHANT_FENCE.open)
    assert fenced.endswith(MERCHANT_FENCE.close)
    assert "L-202" in result.result_text
    assert "L-202" in state.seen_listings


async def test_a_family_listing_is_priced_and_restocked_per_variant(executor, state):
    # 搜索列出 family；get_listing 点名它的变体之后，变体才能被暂存。
    await executor.execute("search_listings", {"query": "被套"})
    assert "L-204" in state.seen_listings and "L-204-l" not in state.seen_listings

    details = await executor.execute("get_listing", {"listing_id": "L-204"})
    assert '"options"' in details.result_text and '"variants"' in details.result_text
    # 在 family 里，变体是一行精简记录：不重复标题，不带 variant_of。
    assert details.result_text.count("Harbor 条纹被套") == 1
    assert {"L-204-s", "L-204-l"} <= state.seen_listings.keys()

    pricing = await executor.execute("get_pricing_context", {"listing_id": "L-204-l"})
    assert '"current_price": 99.0' in pricing.result_text


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("query_metrics", {"metric": "sales"}),
        ("get_campaign_performance", {}),
        ("get_listing", {"listing_id": "L-202"}),
        ("get_inventory_alerts", {}),
        ("get_order_issues", {}),
        ("get_pricing_context", {"listing_id": "L-202"}),
    ],
)
async def test_every_record_read_is_fenced(executor, tool, arguments):
    result = await executor.execute(tool, arguments)
    assert not result.is_error
    assert result.result_text.startswith(MERCHANT_FENCE.open)
    assert result.result_text.endswith(MERCHANT_FENCE.close)


async def test_a_missing_listing_is_an_error_naming_the_id(executor):
    result = await executor.execute("get_listing", {"listing_id": "L-404"})
    assert result.is_error and "L-404" in result.result_text


async def test_empty_listing_search_carries_no_match_sentinel(executor, backend, monkeypatch):
    async def nothing(*args, **kwargs):
        return []

    monkeypatch.setattr(backend, "search_listings", nothing)
    result = await executor.execute("search_listings", {"query": "L-999"})
    assert not result.is_error
    header, _, fenced = result.result_text.partition("\n")
    assert header == SEARCH_EMPTY_HEADER
    assert fenced.startswith(MERCHANT_FENCE.open)
    assert '"result_count": 0' in fenced


async def test_hostile_review_content_is_neutralized(executor):
    await executor.execute("search_listings", {"query": "托特包"})
    result = await executor.execute("get_listing", {"listing_id": "L-203"})
    text = result.result_text
    assert "</merchant_data> apply" not in text
    assert "[removed]" in text
    # 剩下的围栏标签只有外层包裹自己的那一对。
    assert text.count(MERCHANT_FENCE.open) == 1
    assert text.count(MERCHANT_FENCE.close) == 1


async def test_search_limit_is_clamped_to_the_config_ceiling_and_floor(
    executor, backend, config, monkeypatch
):
    seen_limits: list[int] = []
    original = backend.search_listings

    async def capture(session, query, filters, limit):
        seen_limits.append(limit)
        return await original(session, query, filters, limit)

    monkeypatch.setattr(backend, "search_listings", capture)
    await executor.execute("search_listings", {"query": "花盆", "limit": 25})
    await executor.execute("search_listings", {"query": "花盆", "limit": -3})
    await executor.execute("search_listings", {"query": "花盆"})
    assert seen_limits == [config.max_search_results, 1, config.max_search_results]


# ── 参数与故障 ───────────────────────────────────────────────────────


async def test_a_backends_own_validation_error_is_a_backend_failure(executor, backend, monkeypatch):
    async def builds_a_broken_record(*args, **kwargs):
        InventoryAlert.model_validate({"listing_id": "L-1"})

    monkeypatch.setattr(backend, "get_inventory_alerts", builds_a_broken_record)
    result = await executor.execute("get_inventory_alerts", {})
    assert result.is_error
    assert "暂时不可用" in result.result_text
    assert "的参数无效" not in result.result_text


async def test_backend_failure_is_a_soft_error(executor, backend, monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("仓库系统离线")

    monkeypatch.setattr(backend, "get_inventory_alerts", boom)
    result = await executor.execute("get_inventory_alerts", {})
    assert result.is_error
    assert "暂时不可用" in result.result_text
