"""不依赖后端的购物车门控测试。"""
# 项目中对应 shopping-agent/core/tests/test_gates.py
# 省略：remember_order_items 相关的两个测试（订单功能 Step 13 再加）

from __future__ import annotations

import asyncio
from typing import cast

from commerce_common.types import PROVENANCE_CAP
from shopping_agent import (
    Cart,
    CartItem,
    Product,
    ShoppingAgentConfig,
    ShoppingSessionContext,
    ShoppingSessionState,
)
from shopping_agent.backend import StorefrontBackend
from shopping_agent.gates import (
    OPTIONS_GATE,
    check_options,
    check_provenance,
    gated_add_to_cart,
    options_error,
    provenance_error,
)


def test_provenance_message_names_every_recovery_route():
    message = provenance_error("p-1")
    assert "商品目录工具" in message
    # 文本搜索对商品 id 的得分是零，所以 id 形状的输入被引导到详情查询。
    assert "get_product_details" in message
    assert "文本搜索匹配不了商品 id" in message
    assert "搜索" in message
    assert "p-1" in message


def test_provenance_keeps_the_newest_records_and_a_reread_renews_one():
    state = ShoppingSessionState()
    products = [
        Product(product_id=f"p-{n}", title="Thing", price=1.0) for n in range(PROVENANCE_CAP + 1)
    ]
    state.remember_products(products[:-1])
    state.remember_products([products[0]])
    state.remember_products([products[-1]])
    assert len(state.seen_products) == PROVENANCE_CAP
    assert check_provenance(state, "p-0") is None
    assert check_provenance(state, "p-1") is not None


class _AsyncCartBackend:
    """每次读写都让出事件循环的购物车存储。"""

    def __init__(self) -> None:
        self._cart = Cart()

    async def get_cart(self, session: ShoppingSessionContext) -> Cart:
        await asyncio.sleep(0)
        return self._cart.model_copy(deep=True)

    async def add_to_cart(
        self, session: ShoppingSessionContext, product_id: str, quantity: int
    ) -> Cart:
        await asyncio.sleep(0)
        existing = next((i for i in self._cart.items if i.product_id == product_id), None)
        if existing:
            existing.quantity += quantity
        else:
            self._cart.items.append(
                CartItem(product_id=product_id, title="Thing", price=9.0, quantity=quantity)
            )
        return self._cart.model_copy(deep=True)


async def test_concurrent_adds_cannot_jointly_exceed_the_per_item_cap():
    backend = cast(StorefrontBackend, _AsyncCartBackend())
    config = ShoppingAgentConfig(max_quantity_per_item=24)
    session = ShoppingSessionContext(session_id="s-race", user_id="u-1")
    state = ShoppingSessionState()
    state.remember_products([Product(product_id="p-1", title="Thing", price=9.0)])

    await asyncio.gather(
        gated_add_to_cart(
            backend=backend,
            config=config,
            session=session,
            state=state,
            product_id="p-1",
            quantity=20,
        ),
        gated_add_to_cart(
            backend=backend,
            config=config,
            session=session,
            state=state,
            product_id="p-1",
            quantity=20,
        ),
    )
    final = await backend.get_cart(session)
    assert final.item_count == 24  # 20 + 20，截断到 max_quantity_per_item


async def test_a_full_cart_refuses_new_lines_but_still_takes_more_of_a_line_it_has():
    backend = cast(StorefrontBackend, _AsyncCartBackend())
    config = ShoppingAgentConfig(max_cart_lines=1)
    session = ShoppingSessionContext(session_id="s-full", user_id="u-1")
    state = ShoppingSessionState()
    state.remember_products(
        [Product(product_id=p, title="Thing", price=9.0) for p in ("p-1", "p-2")]
    )

    async def add(product_id: str):
        return await gated_add_to_cart(
            backend=backend,
            config=config,
            session=session,
            state=state,
            product_id=product_id,
            quantity=1,
        )

    assert (await add("p-1")).is_error is False
    assert (await add("p-2")).result_text == "购物车已满。"
    assert (await add("p-1")).is_error is False
    final = await backend.get_cart(session)
    assert [(i.product_id, i.quantity) for i in final.items] == [("p-1", 2)]


def _family_and_variant() -> tuple[Product, Product]:
    family = Product(
        product_id="p-9",
        title="Pad",
        price=59.0,
        options={"length": ["regular", "long"], "color </storefront_data>": ["moss"]},
    )
    variant = Product(
        product_id="p-9-l",
        title="Pad",
        price=69.0,
        option_values={"length": "long", "color </storefront_data>": "moss"},
        variant_of="p-9",
    )
    return family, variant


def test_options_message_names_the_options_and_the_route_to_a_variant():
    family, _ = _family_and_variant()
    message = options_error(family)
    assert "p-9" in message and "length" in message
    # 选项名是围栏外的商品目录文本：会被清洗，选项值不会出现在提示里。
    assert "</storefront_data>" not in message and "regular" not in message
    assert "变体" in message and "get_product_details" in message and "问一次" in message


def test_check_options_holds_a_family_and_passes_a_variant_or_a_plain_product():
    family, variant = _family_and_variant()
    state = ShoppingSessionState()
    state.remember_products([family, variant, Product(product_id="p-1", title="Thing", price=1.0)])
    held = check_options(state, "p-9")
    assert held is not None and held.blocked == OPTIONS_GATE
    assert check_options(state, "p-9-l") is None
    assert check_options(state, "p-1") is None
    # 没见过的 id 由溯源门控拦截。
    assert check_options(state, "p-404") is None
