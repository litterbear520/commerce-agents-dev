"""购物车门控。购物车写操作只接受本次会话中商品目录工具返回过的 product_id
（或购物车中已有的行），拦截仍有选项未选的 family 商品并引导选择变体，
将行数量截断到配置的上限，并报告截断情况；
同一会话的写操作串行执行，因为一轮的工具调用是并发的。
"""
# 项目中对应 shopping-agent/core/shopping_agent/gates.py
# 当前不含 remember_order_items（订单功能 Step 13 再加）

from __future__ import annotations

import asyncio
import weakref

from .backend import StorefrontBackend
from .config import ShoppingAgentConfig
from .fencing import STOREFRONT_FENCE
from .outcome import ToolOutcome
from .types import Product, ShoppingSessionContext, ShoppingSessionState

PROVENANCE_GATE = "provenance"
OPTIONS_GATE = "options"


def provenance_error(product_id: str) -> str:
    # 提示里 get_product_details 放在前面：文本搜索匹配不了 id，
    # 空搜索结果会让模型以为商品不存在
    return (
        f"product_id {product_id} 不是本次会话中商品目录工具返回的。"
        "请先确认：用这个 id 调用 get_product_details（文本搜索匹配不了商品 id），"
        "或者通过搜索找到它，然后用搜索结果中的 product_id 加购。"
    )


def check_provenance(state: ShoppingSessionState, product_id: str) -> ToolOutcome | None:
    """``product_id`` 没有会话溯源时返回 held，否则返回 None。"""
    if product_id in state.seen_products:
        return None
    return ToolOutcome.held(PROVENANCE_GATE, provenance_error(product_id))


def options_error(product: Product) -> str:
    # 选项名是围栏外的商品目录文本，需要清洗并限制长度
    names = STOREFRONT_FENCE.sanitize_text(", ".join(product.options))[:60]
    return (
        f"product_id {product.product_id} 还有选项未选（{names}），"
        "购物车只接受它的变体。请根据顾客的要求或偏好确定每个选项，"
        "如有一个选项还不确定就用选项值作为快捷按钮问一次，"
        "然后用 get_product_details 返回的变体 product_id 加购。"
    )


def check_options(state: ShoppingSessionState, product_id: str) -> ToolOutcome | None:
    """``product_id`` 对应的记录是仍有选项未选的 family 商品时返回 held；
    购物车接受的是它的变体。"""
    product = state.seen_products.get(product_id)
    if product is None or not product.has_options:
        return None
    return ToolOutcome.held(OPTIONS_GATE, options_error(product))


# ── 写锁 ────────────────────────────────────────────────────────────
# 门控先读购物车再写，同一会话的第二次写操作不能和它交错
# 锁只在被持有时存活（WeakValueDictionary）

_cart_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()


def _cart_lock(session: ShoppingSessionContext) -> asyncio.Lock:
    lock = _cart_locks.get(session.session_id)
    if lock is None:
        lock = _cart_locks[session.session_id] = asyncio.Lock()
    return lock


# ── gated 写操作 ─────────────────────────────────────────────────────


async def gated_add_to_cart(
    *,
    backend: StorefrontBackend,
    config: ShoppingAgentConfig,
    session: ShoppingSessionContext,
    state: ShoppingSessionState,
    product_id: str,
    quantity: int,
) -> ToolOutcome:
    if held := check_provenance(state, product_id) or check_options(state, product_id):
        return held
    requested = max(1, quantity)
    max_quantity = config.max_quantity_per_item
    async with _cart_lock(session):
        current = await backend.get_cart(session)
        existing = next((i for i in current.items if i.product_id == product_id), None)
        if existing is None and len(current.items) >= config.max_cart_lines:
            return ToolOutcome.error("购物车已满。")
        allowed = min(
            requested,
            max(0, max_quantity - (existing.quantity if existing else 0)),
        )
        if allowed <= 0:
            return ToolOutcome.error(f"该商品已达到单品上限 {max_quantity} 件。")
        cart = await backend.add_to_cart(session, product_id, allowed)
    capped = f"（已截断到单品上限 {max_quantity} 件）" if allowed < requested else ""
    return ToolOutcome(
        f"已加购 {product_id} x{allowed}{capped}。"
        f"购物车：{cart.item_count} 件商品，小计 {cart.currency} {cart.subtotal}。"
    )


async def gated_update_cart_item(
    *,
    backend: StorefrontBackend,
    config: ShoppingAgentConfig,
    session: ShoppingSessionContext,
    state: ShoppingSessionState,
    product_id: str,
    quantity: int,
) -> ToolOutcome:
    requested = max(1, quantity)
    applied = min(requested, config.max_quantity_per_item)
    async with _cart_lock(session):
        if held := await _check_provenance_or_cart(backend, session, state, product_id):
            return held
        cart = await backend.update_cart_item(session, product_id, applied)
    capped = (
        f"（已截断到单品上限 {config.max_quantity_per_item} 件）" if applied < requested else ""
    )
    return ToolOutcome(
        f"已更新数量{capped}。"
        f"购物车：{cart.item_count} 件商品，小计 {cart.currency} {cart.subtotal}。"
    )


async def gated_remove_from_cart(
    *,
    backend: StorefrontBackend,
    session: ShoppingSessionContext,
    state: ShoppingSessionState,
    product_id: str,
) -> ToolOutcome:
    async with _cart_lock(session):
        if held := await _check_provenance_or_cart(backend, session, state, product_id):
            return held
        cart = await backend.remove_from_cart(session, product_id)
    return ToolOutcome(
        f"已移除。购物车：{cart.item_count} 件商品，小计 {cart.currency} {cart.subtotal}。"
    )


async def _check_provenance_or_cart(
    backend: StorefrontBackend,
    session: ShoppingSessionContext,
    state: ShoppingSessionState,
    product_id: str,
) -> ToolOutcome | None:
    """update 和 remove 也接受购物车中已有的行（可能早于本次会话）；
    只有溯源不通过时才去取购物车检查。"""
    if check_provenance(state, product_id) is None:
        return None
    current = await backend.get_cart(session)
    if any(item.product_id == product_id for item in current.items):
        return None
    return ToolOutcome.held(PROVENANCE_GATE, provenance_error(product_id))
