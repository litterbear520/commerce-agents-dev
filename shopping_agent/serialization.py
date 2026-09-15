"""读取类工具返回给模型的数据格式，统一构建以确保每条路径返回相同的字节。
搜索结果的头部是围栏外唯一由运行时生成的一行：结果数量和一句固定的说明，
告诉模型如何理解这些结果是文本匹配（零结果时额外说明 id 要通过
get_product_details 解析）。只有数量会变。
"""
# 项目中对应 shopping-agent/core/shopping_agent/serialization.py
# 当前只包含商品和购物车的序列化，order/policy/fulfillment 到 Step 13 再加

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .fencing import STOREFRONT_FENCE
from .types import Cart, CartItem, Product, ProductDetails


def compact_product(product: Product) -> dict[str, Any]:
    # 搜索结果中一条商品的精简表示：去掉值为 None 或空的字段
    data = {
        "product_id": product.product_id,
        "title": product.title,
        "brand": product.brand,
        "price": product.price,
        "currency": product.currency,
        "rating": product.rating,
        "review_count": product.review_count,
        "in_stock": product.in_stock,
        "labels": product.labels or None,
        "attributes": product.attributes or None,
        "options": product.options or None,
        "option_values": product.option_values or None,
        "variant_of": product.variant_of,
        "short_description": product.short_description,
    }
    return {k: v for k, v in data.items() if v is not None}


_VARIANT_ALWAYS = ("product_id", "option_values", "price", "in_stock")


def variant_row(variant: Product, family: dict[str, Any]) -> dict[str, Any]:
    """family 记录中的一个变体：id、选项值、价格、库存，
    以及与 family 不同的字段，让一长串尺码变体保持简短。"""
    row = compact_product(variant)
    row.pop("variant_of", None)
    attributes = {
        k: v for k, v in variant.attributes.items() if (family.get("attributes") or {}).get(k) != v
    }
    kept = {
        k: v
        for k, v in row.items()
        if k in _VARIANT_ALWAYS or (k != "attributes" and family.get(k) != v)
    }
    lead = {
        "product_id": kept.pop("product_id"),
        "option_values": kept.pop("option_values", {}),
    }
    return lead | kept | ({"attributes": attributes} if attributes else {})


def product_details_payload(details: ProductDetails) -> dict[str, Any]:
    # 商品详情的完整数据，变体用 variant_row 精简
    family = compact_product(details)
    payload = family | {
        "long_description": details.long_description,
        "specs": details.specs or None,
        "review_highlights": details.review_highlights or None,
        "variants": [variant_row(v, family) for v in details.variants] or None,
    }
    return {k: v for k, v in payload.items() if v is not None}


# ── 搜索结果 ─────────────────────────────────────────────────────────

SEARCH_EMPTY_HEADER = (
    "搜索返回 0 条结果：目录中没有匹配此查询的商品。"
    "在告知顾客没有该商品之前，先用更宽泛的关键词重试一次，"
    "不要把其他商品当作顾客要找的那个。"
    "搜索匹配的是商品文本而非 id；要解析商品 id 请用 get_product_details。"
)


def search_result_header(count: int) -> str:
    # 搜索结果头部：围栏外的一行说明
    if count == 0:
        return SEARCH_EMPTY_HEADER
    return (
        f"搜索返回 {count} 条结果：目录中最接近的文本匹配，"
        "可能包含相关商品而非顾客要找的那个。"
        "只有标题和属性都匹配时才算是顾客要的商品；"
        "如果都不匹配则说明没找到，推荐的替代品要明确说明是替代。"
    )


def search_result_text(query: str, products: Sequence[Product]) -> str:
    """完整的 search_products 返回结果：头部说明 + 围栏包裹的数据。"""
    payload = {
        "query": query,
        "result_count": len(products),
        "results": [compact_product(p) for p in products],
    }
    fenced = STOREFRONT_FENCE.fence_payload(payload)
    return search_result_header(len(products)) + "\n" + fenced


# ── 购物车 ───────────────────────────────────────────────────────────


def cart_summary(cart: Cart) -> str:
    # 门控确认文本中的购物车摘要
    return f"{cart.item_count} 件商品，小计 {cart.subtotal:.2f} {cart.currency}"


def cart_line_payload(item: CartItem) -> dict[str, Any]:
    # 购物车单行，附加 line_total，去掉空的 option_values/variant_of
    line = item.model_dump() | {"line_total": item.line_total}
    for key in ("option_values", "variant_of"):
        if not line[key]:
            del line[key]
    return line


def cart_payload(cart: Cart) -> dict[str, Any]:
    # 购物车的完整数据
    return {
        "items": [cart_line_payload(item) for item in cart.items],
        "item_count": cart.item_count,
        "subtotal": cart.subtotal,
        "currency": cart.currency,
    }
