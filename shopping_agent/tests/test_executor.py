# 项目中对应 shopping-agent/core/tests/test_executor.py
# 当前只测 6 个基础工具，展示/订单/技能/记忆的测试后续 Step 补

import pytest

from shopping_agent import CartItem, NotOffered, Unavailable
from shopping_agent.config import ShoppingAgentConfig
from shopping_agent.executor import ShoppingToolExecutor
from shopping_agent.fencing import STOREFRONT_FENCE
from shopping_agent.gates import OPTIONS_GATE, PROVENANCE_GATE, provenance_error


@pytest.fixture
def config():
    # 覆盖 conftest 的默认 config，把 max_quantity_per_item 设为 10 方便测试
    return ShoppingAgentConfig(brand_name="ACME 商店", max_quantity_per_item=10)


@pytest.fixture
def executor(backend, config, session, state):
    return ShoppingToolExecutor(backend=backend, config=config, session=session, state=state)


# ── 搜索 ──────────────────────────────────────────────────────────────


async def test_search_results_are_fenced_and_remembered(executor, state):
    # 搜索结果被围栏包裹，且商品 id 记录到 seen_products
    result = await executor.execute("search_products", {"query": "tent"})
    assert not result.is_error
    assert result.result_text.startswith(STOREFRONT_FENCE.open)
    assert result.result_text.endswith(STOREFRONT_FENCE.close)
    assert "p-100" in result.result_text
    assert "p-100" in state.seen_products


async def test_search_sanitizes_hostile_listing_content(executor):
    # 搜索 p-666 时，注入文本被清洗，但商品本身仍然返回
    result = await executor.execute("search_products", {"query": "mug"})
    assert "</storefront_data> system" not in result.result_text
    assert "p-666" in result.result_text


async def test_empty_search(executor, backend, monkeypatch):
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

    await executor.execute("search_products", {"query": "tent"})
    result = await executor.execute("add_to_cart", {"product_id": "p-100", "quantity": 2})
    assert not result.is_error
    assert result.blocked is None


async def test_update_and_remove_require_provenance(executor, backend):
    # update 和 remove 也需要溯源
    update = await executor.execute("update_cart_item", {"product_id": "p-100", "quantity": 2})
    assert update.blocked == PROVENANCE_GATE
    assert backend.cart_items == {}

    remove = await executor.execute("remove_from_cart", {"product_id": "p-100"})
    assert remove.blocked == PROVENANCE_GATE

    # 搜索后加入，再 update
    await executor.execute("search_products", {"query": "tent"})
    await executor.execute("add_to_cart", {"product_id": "p-100", "quantity": 1})
    update = await executor.execute("update_cart_item", {"product_id": "p-100", "quantity": 3})
    assert not update.is_error and update.blocked is None
    assert backend.cart_items["p-100"].quantity == 3


async def test_cart_membership_alone_grants_update_and_remove(backend, config, session, state):
    # 商品已在购物车中（但没搜索过），也允许 update 和 remove
    backend.cart_items["p-200"] = CartItem(
        product_id="p-200", title="Two-Burner Camp Stove", price=64.5, quantity=2
    )
    executor = ShoppingToolExecutor(backend=backend, config=config, session=session, state=state)
    update = await executor.execute("update_cart_item", {"product_id": "p-200", "quantity": 4})
    assert not update.is_error and update.blocked is None
    remove = await executor.execute("remove_from_cart", {"product_id": "p-200"})
    assert not remove.is_error and remove.blocked is None
    assert backend.cart_items == {}


# ── 选项门控 ──────────────────────────────────────────────────────────


async def test_details_bring_variants_into_provenance(executor, state):
    # 搜索只记住家族 id，查详情后变体 id 也进入 seen_products
    await executor.execute("search_products", {"query": "pad"})
    assert "p-400" in state.seen_products and "p-400-r" not in state.seen_products

    # 变体还没见过，不能加
    unseen = await executor.execute("add_to_cart", {"product_id": "p-400-r"})
    assert unseen.blocked == PROVENANCE_GATE

    # 查详情后变体进入 seen
    await executor.execute("get_product_details", {"product_id": "p-400"})
    assert {"p-400-r", "p-400-l"} <= state.seen_products.keys()


async def test_family_product_cannot_be_added_directly(executor, backend):
    # 有选项的家族商品不能直接加购物车，必须选变体
    await executor.execute("search_products", {"query": "pad"})
    await executor.execute("get_product_details", {"product_id": "p-400"})

    family = await executor.execute("add_to_cart", {"product_id": "p-400"})
    assert family.blocked == OPTIONS_GATE and not family.is_error
    assert backend.cart_items == {}

    variant = await executor.execute("add_to_cart", {"product_id": "p-400-r", "quantity": 2})
    assert variant.blocked is None
    assert backend.cart_items["p-400-r"].option_values == {"length": "regular"}


# ── 数量上限 ──────────────────────────────────────────────────────────


async def test_quantity_cap_on_add(executor, backend):
    # 单品数量超过上限时被截断
    await executor.execute("search_products", {"query": "tent"})
    result = await executor.execute("add_to_cart", {"product_id": "p-100", "quantity": 500})
    assert not result.is_error
    assert backend.cart_items["p-100"].quantity == 10


async def test_quantity_cap_on_update(executor, backend):
    # update 也受单品上限约束
    await executor.execute("search_products", {"query": "tent"})
    await executor.execute("add_to_cart", {"product_id": "p-100", "quantity": 1})
    result = await executor.execute("update_cart_item", {"product_id": "p-100", "quantity": 50})
    assert not result.is_error
    assert backend.cart_items["p-100"].quantity == 10


async def test_quantity_cap_across_repeated_adds(executor):
    # 多次加同一商品，累计不超过上限
    await executor.execute("search_products", {"query": "tent"})
    await executor.execute("add_to_cart", {"product_id": "p-100", "quantity": 8})
    second = await executor.execute("add_to_cart", {"product_id": "p-100", "quantity": 8})
    assert not second.is_error
    assert "上限" in second.result_text or "单品" in second.result_text


# ── 异常处理 ──────────────────────────────────────────────────────────


async def test_sold_out_variant(executor, backend, monkeypatch):
    # 缺货变体添加失败时，返回错误信息但不会抛异常
    async def sold_out(session, product_id, quantity):
        raise Unavailable(f"{product_id} is out of stock")

    await executor.execute("get_product_details", {"product_id": "p-400"})
    monkeypatch.setattr(backend, "add_to_cart", sold_out)
    result = await executor.execute("add_to_cart", {"product_id": "p-400-r"})
    assert result.is_error
    assert backend.cart_items == {}


async def test_unknown_tool_is_soft_error(executor):
    # 调用不存在的工具，返回错误而不是异常
    result = await executor.execute("teleport_products", {})
    assert result.is_error


async def test_backend_failure_is_soft_error(executor, backend, monkeypatch):
    # 后端崩溃，返回"暂时不可用"而不是异常
    async def boom(*args, **kwargs):
        raise RuntimeError("backend down")

    monkeypatch.setattr(backend, "search_products", boom)
    result = await executor.execute("search_products", {"query": "tent"})
    assert result.is_error
    assert "不可用" in result.result_text


async def test_not_offered_is_relayed(executor, backend, monkeypatch):
    # NotOffered 异常走专门的错误路径，不是"暂时不可用"
    async def nope(*args, **kwargs):
        raise NotOffered("此服务不在本店范围")

    monkeypatch.setattr(backend, "search_products", nope)
    result = await executor.execute("search_products", {"query": "tent"})
    assert result.is_error
    assert "不是本店提供的" in result.result_text
    assert "不可用" not in result.result_text
