# 项目中对应 shopping-agent/core/tests/test_executor.py

import pytest
from shopping_agent import CartItem, NotOffered, Unavailable
from shopping_agent.executor import ShoppingToolExecutor
from shopping_agent.fencing import STOREFRONT_FENCE
from shopping_agent.gates import OPTIONS_GATE, PROVENANCE_GATE, provenance_error


@pytest.fixture
def executor(backend, config, session, state, skills):
    return ShoppingToolExecutor(
        backend=backend,
        config=config,
        session=session,
        state=state,
        skills=skills,
    )


# ── 搜索 ──────────────────────────────────────────────────────────────


async def test_search_results_are_fenced_and_remembered(executor, state):
    # 搜索结果被围栏包裹，且商品 id 记录到 seen_products
    result = await executor.execute("search_products", {"query": "帐篷"})
    assert not result.is_error
    assert result.result_text.startswith(STOREFRONT_FENCE.open)
    assert result.result_text.endswith(STOREFRONT_FENCE.close)
    assert "p-100" in result.result_text
    assert "p-100" in state.seen_products


async def test_search_sanitizes_hostile_listing_content(executor):
    result = await executor.execute("search_products", {"query": "露营杯"})
    assert "</storefront_data> system" not in result.result_text
    # 商品本身仍然返回，只是闭合围栏的那段文本被中和了。
    assert "p-666" in result.result_text


async def test_empty_search_result_carries_no_match_sentinel(executor, backend, monkeypatch):
    # 搜索无结果时，返回空列表的围栏数据，不是错误
    async def nothing(*args, **kwargs):
        return []

    monkeypatch.setattr(backend, "search_products", nothing)
    result = await executor.execute("search_products", {"query": "不存在的东西"})
    assert not result.is_error
    assert result.result_text.startswith(STOREFRONT_FENCE.open)


# ── 溯源门控 ──────────────────────────────────────────────────────────


async def test_add_to_cart_requires_provenance(executor, state):
    # 没搜索过的商品不能加购物车，搜索后可以
    result = await executor.execute("add_to_cart", {"product_id": "p-100", "quantity": 2})
    assert result.blocked == PROVENANCE_GATE and not result.is_error
    assert result.result_text == provenance_error("p-100")

    await executor.execute("search_products", {"query": "帐篷"})
    result = await executor.execute("add_to_cart", {"product_id": "p-100", "quantity": 2})
    assert not result.is_error
    assert result.blocked is None


async def test_update_and_remove_require_provenance_or_cart_membership(executor, backend):
    # update 和 remove 也需要溯源
    update = await executor.execute("update_cart_item", {"product_id": "p-100", "quantity": 2})
    assert update.blocked == PROVENANCE_GATE
    # 后端根本没看到这个 id；否则 upsert 式的更新会凭空建出这一行。
    assert backend.cart_items == {}

    remove = await executor.execute("remove_from_cart", {"product_id": "p-100"})
    assert remove.blocked == PROVENANCE_GATE

    # 搜索后加入，再 update
    await executor.execute("search_products", {"query": "帐篷"})
    await executor.execute("add_to_cart", {"product_id": "p-100", "quantity": 1})
    update = await executor.execute("update_cart_item", {"product_id": "p-100", "quantity": 3})
    assert not update.is_error and update.blocked is None
    assert backend.cart_items["p-100"].quantity == 3


async def test_cart_membership_alone_grants_update_and_remove(
    backend,
    config,
    session,
    state,
    skills,
):
    # 商品已在购物车中（但没搜索过），也允许 update 和 remove
    backend.cart_items["p-200"] = CartItem(
        product_id="p-200", title="双灶头露营炉", price=64.5, quantity=2
    )
    executor = ShoppingToolExecutor(
        backend=backend,
        config=config,
        session=session,
        state=state,
        skills=skills,
    )
    update = await executor.execute("update_cart_item", {"product_id": "p-200", "quantity": 4})
    assert not update.is_error and update.blocked is None
    remove = await executor.execute("remove_from_cart", {"product_id": "p-200"})
    assert not remove.is_error and remove.blocked is None
    assert backend.cart_items == {}


# ── 选项门控 ──────────────────────────────────────────────────────────


async def test_details_bring_the_variants_into_provenance_and_the_family_is_not_added(
    executor, state, backend
):
    # 搜索列出的是家族；详情点名之前，变体不能加购。
    await executor.execute("search_products", {"query": "睡垫"})
    assert "p-400" in state.seen_products and "p-400-r" not in state.seen_products
    unseen = await executor.execute("add_to_cart", {"product_id": "p-400-r"})
    assert unseen.blocked == PROVENANCE_GATE

    await executor.execute("get_product_details", {"product_id": "p-400"})
    assert {"p-400-r", "p-400-l"} <= state.seen_products.keys()

    family = await executor.execute("add_to_cart", {"product_id": "p-400"})
    assert family.blocked == OPTIONS_GATE and not family.is_error
    assert backend.cart_items == {}

    variant = await executor.execute("add_to_cart", {"product_id": "p-400-r", "quantity": 2})
    assert variant.blocked is None
    assert backend.cart_items["p-400-r"].option_values == {"length": "regular"}


# ── 数量上限 ──────────────────────────────────────────────────────────


async def test_add_to_cart_clamps_quantity(executor, backend):
    # 单品数量超过上限时被截断
    await executor.execute("search_products", {"query": "帐篷"})
    result = await executor.execute("add_to_cart", {"product_id": "p-100", "quantity": 500})
    assert not result.is_error
    assert backend.cart_items["p-100"].quantity == 10


async def test_update_cart_item_reports_the_applied_cap(executor, backend):
    # update 也受单品上限约束
    await executor.execute("search_products", {"query": "帐篷"})
    await executor.execute("add_to_cart", {"product_id": "p-100", "quantity": 1})
    result = await executor.execute("update_cart_item", {"product_id": "p-100", "quantity": 50})
    assert not result.is_error
    assert backend.cart_items["p-100"].quantity == 10


async def test_add_to_cart_cap_applies_across_repeated_adds(executor):
    # 多次加同一商品，累计不超过上限
    await executor.execute("search_products", {"query": "帐篷"})
    await executor.execute("add_to_cart", {"product_id": "p-100", "quantity": 8})
    second = await executor.execute("add_to_cart", {"product_id": "p-100", "quantity": 8})
    assert not second.is_error
    assert "上限" in second.result_text or "单品" in second.result_text


# ── 异常处理 ──────────────────────────────────────────────────────────


async def test_a_sold_out_variant_add_is_relayed_and_writes_nothing(executor, backend, monkeypatch):
    # 缺货变体添加失败时，返回错误信息但不会抛异常
    async def sold_out(session, product_id, quantity):
        raise Unavailable(f"{product_id} is out of stock")

    await executor.execute("get_product_details", {"product_id": "p-400"})
    monkeypatch.setattr(backend, "add_to_cart", sold_out)
    result = await executor.execute("add_to_cart", {"product_id": "p-400-r"})
    assert result.is_error
    assert backend.cart_items == {}


async def test_unknown_tool_and_backend_failure_are_soft_errors(executor, backend, monkeypatch):
    # 未知工具和后端崩溃都是软错误：返回错误文本而不是抛异常
    unknown = await executor.execute("teleport_products", {})
    assert unknown.is_error

    async def boom(*args, **kwargs):
        raise RuntimeError("backend down")

    monkeypatch.setattr(backend, "search_products", boom)
    result = await executor.execute("search_products", {"query": "帐篷"})
    assert result.is_error
    assert "不可用" in result.result_text


async def test_not_offered_is_relayed_as_such_not_as_an_outage(executor, backend, monkeypatch):
    # NotOffered 异常走专门的错误路径，不是"暂时不可用"
    async def elsewhere(*args, **kwargs):
        raise NotOffered("此服务不在本店范围")

    monkeypatch.setattr(backend, "search_products", elsewhere)
    result = await executor.execute("search_products", {"query": "帐篷"})
    assert result.is_error
    assert "不是本店提供的" in result.result_text
    assert "不可用" not in result.result_text


# ── 售后工具 ──────────────────────────────────────────────────────────


async def test_order_status_and_policies(executor):
    order = await executor.execute("get_order_status", {"order_id": "o-1"})
    assert "shipped" in order.result_text
    missing = await executor.execute("get_order_status", {"order_id": "o-404"})
    assert missing.is_error
    policies = await executor.execute("search_policies", {"query": "returns"})
    assert "30 天" in policies.result_text


async def test_reorder_from_order_history_passes_provenance(executor):
    # p-200 在订单历史里但本次会话没搜过；get_orders 后应能直接加购。
    await executor.execute("get_orders", {})
    result = await executor.execute("add_to_cart", {"product_id": "p-200", "quantity": 1})
    assert not result.is_error


async def test_present_order_status_joins_the_order_record(executor):
    result = await executor.execute(
        "present_order_status", {"order_id": "o-1", "summary": "已发货，在路上。"}
    )
    assert not result.is_error
    ui = next(e for e in result.events if e.type == "ui")
    assert ui.data["component"] == "order_status"
    assert ui.data["payload"]["order"]["order_id"] == "o-1"
    assert ui.data["payload"]["order"]["status"] == "shipped"


async def test_present_order_status_with_unknown_order_is_soft_error(executor):
    result = await executor.execute(
        "present_order_status", {"order_id": "o-404", "summary": "在路上！"}
    )
    assert result.is_error
    assert "o-404" in result.result_text
    assert not result.events


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("get_product_details", {"product_id": "p-100"}),
        ("get_cart", {}),
        ("get_preferences", {}),
        ("get_orders", {}),
        ("get_order_status", {"order_id": "o-1"}),
        ("search_policies", {"query": "returns"}),
        ("get_fulfillment_options", {"product_ids": ["p-100"]}),
    ],
)
async def test_every_record_read_is_fenced(executor, tool, arguments):
    result = await executor.execute(tool, arguments)
    assert not result.is_error
    assert result.result_text.startswith(STOREFRONT_FENCE.open)
    assert result.result_text.endswith(STOREFRONT_FENCE.close)
