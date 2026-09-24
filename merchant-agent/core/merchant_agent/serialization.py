"""search_listings 的返回结果，统一构建一次，所以每条路径返回相同的字节。头部是围栏外
唯一由运行时写的一行：结果数量，加一句固定的话，说明这些结果要当作文本匹配来读
（零结果的版本还说明 id 要通过 get_listing 解析）。只有数量会变。"""
# 项目中对应 merchant-agent/core/merchant_agent/serialization.py

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from commerce_common.fencing import MAX_FENCED_CHARS

from .fencing import MERCHANT_FENCE
from .types import InventoryAlert, Listing, ListingDetails, PricingContext

_VARIANT_ALWAYS = ("listing_id", "option_values", "price", "stock", "status")
_PRICING_ALWAYS = ("listing_id", "option_values", "current_price", "unit_cost", "margin_pct")


def listing_record(listing: Listing) -> dict[str, Any]:
    """模型读到的一条商品条目；普通商品不带选项相关的键。"""
    row = listing.model_dump(mode="json", exclude_none=True)
    for key in ("options", "option_values", "variants"):
        if not row.get(key):
            row.pop(key, None)
    return row


def variant_row(variant: Listing, family: dict[str, Any]) -> dict[str, Any]:
    """family 记录里的一个变体：id、选项值、价格、库存、状态，
    以及只在和 family 不同时才带的字段和属性。"""
    row = listing_record(variant)
    for key in ("variant_of", "options", "variants"):
        row.pop(key, None)
    attributes = {
        k: v for k, v in variant.attributes.items() if (family.get("attributes") or {}).get(k) != v
    }
    kept = {
        k: v
        for k, v in row.items()
        if k in _VARIANT_ALWAYS or (k != "attributes" and family.get(k) != v)
    }
    lead = {"listing_id": kept.pop("listing_id"), "option_values": kept.pop("option_values", {})}
    return lead | kept | ({"attributes": attributes} if attributes else {})


def listing_details_payload(details: ListingDetails) -> dict[str, Any]:
    """get_listing 的返回结果：商品条目记录，family 的变体用精简行表示。"""
    family = listing_record(details)
    family.pop("variants", None)
    rows = [variant_row(v, family) for v in details.variants]
    return family | ({"variants": rows} if rows else {})


SEARCH_EMPTY_HEADER = (
    "搜索返回 0 条结果：店里没有商品条目匹配这个查询。如实说明——不要描述没有返回的"
    "商品条目。注意：搜索匹配的是商品条目的文字，不是 id；要解析商品条目 id 请用 get_listing。"
)


def search_result_header(count: int) -> str:
    if count == 0:
        return SEARCH_EMPTY_HEADER
    return (
        f"搜索返回 {count} 条结果：最接近的文本匹配——在报告或暂存之前，"
        "先确认这就是要找的那条商品条目。"
    )


def search_result_text(
    query: str, listings: Sequence[Listing], max_chars: int = MAX_FENCED_CHARS
) -> str:
    """完整的 search_listings 返回结果：头部一行，然后是围栏包裹的数据。"""
    payload = {
        "query": query,
        "result_count": len(listings),
        "results": [listing_record(listing) for listing in listings],
    }
    header = search_result_header(len(listings))
    return header + "\n" + MERCHANT_FENCE.fence_payload(payload, max_chars)


def pricing_context_payload(context: PricingContext) -> dict[str, Any]:
    """get_pricing_context 的返回结果；family 的各变体参考数据去掉和 family 那行
    相同的上限和币种。"""
    payload = context.model_dump(exclude_none=True, exclude={"variants"})
    if not payload.get("option_values"):
        payload.pop("option_values", None)
    rows = []
    for variant in context.variants:
        row = variant.model_dump(exclude_none=True, exclude={"variants"})
        rows.append({k: v for k, v in row.items() if k in _PRICING_ALWAYS or payload.get(k) != v})
    return payload | ({"variants": rows} if rows else {})


def alert_record(alert: InventoryAlert) -> dict[str, Any]:
    row = alert.model_dump(exclude_none=True)
    if not row.get("option_values"):
        row.pop("option_values", None)
    return row
