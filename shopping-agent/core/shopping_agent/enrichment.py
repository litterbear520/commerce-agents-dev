"""内置展示组件的补全钩子：每个 payload 和会话的商品记录、购物车
或订单拼接后再交给调用方。没有会话溯源的 id 会被丢弃并报告；
一个组件如果没有任何可靠数据可展示，就会被拒绝。
"""
# 项目中对应 shopping-agent/core/shopping_agent/enrichment.py
# enrich_disclosure → Step 28 再加

from __future__ import annotations

from typing import Any

from commerce_common.presentation import (
    CHIPS_COMPONENT,
    CHIPS_TOOL,
    EnrichmentContext,
    PresentationComponent,
    PresentationRefused,
    PresentSuggestionsPayload,
)

from .gates import PROVENANCE_GATE
from .serialization import cart_payload
from .tools.presentation import (
    CheckoutPayload,
    PresentComparisonPayload,
    PresentGuidePayload,
    PresentOrderStatusPayload,
    PresentPlanPayload,
    PresentProductsPayload,
)
from .types import Product, ShoppingSessionState

# ── 辅助函数 ────────────────────────────────────────────────────────


def _record(product: Product) -> dict[str, Any]:
    return product.model_dump(exclude_none=True)


def _resolve(
    state: ShoppingSessionState, product_ids: list[str], dropped: list[str]
) -> list[dict[str, Any]]:
    records = []
    for product_id in product_ids:
        product = state.seen_products.get(product_id)
        (records.append(_record(product)) if product else dropped.append(product_id))
    return records


def _note_dropped(context: EnrichmentContext, dropped: list[str]) -> None:
    if dropped:
        context.notes.append(f"跳过了本次会话未出现过的 product_id：{', '.join(dropped)}")


# ── 价差计算 ────────────────────────────────────────────────────────


def comparison_price_delta(entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    """补全后的对比条目中最便宜和最贵之间的价差；不足两条有价格、
    价差为零、或币种不同时返回 None。"""
    if len({entry.get("product", {}).get("currency", "USD") for entry in entries}) > 1:
        return None
    priced = sorted(
        (entry["product"]["price"], entry["product_id"])
        for entry in entries
        if entry.get("product", {}).get("price") is not None
    )
    if len(priced) < 2:
        return None
    (low_price, low_id), (high_price, high_id) = priced[0], priced[-1]
    amount = round(high_price - low_price, 2)
    if amount <= 0:
        return None
    return {
        "amount": amount,
        "low_product_id": low_id,
        "low_price": low_price,
        "high_product_id": high_id,
        "high_price": high_price,
    }


# ── 补全钩子 ────────────────────────────────────────────────────────


async def enrich_products(
    payload: PresentProductsPayload, context: EnrichmentContext
) -> dict[str, Any]:
    dropped: list[str] = []
    items = []
    for pick in payload.picks:
        product = context.state.seen_products.get(pick.product_id)
        if product is None:
            dropped.append(pick.product_id)
            continue
        items.append({"product": _record(product), "reason": pick.reason})
    if not items:
        raise PresentationRefused(
            "这些 product_id 都不是本次会话的搜索结果，请先搜索再从结果中选择。",
            PROVENANCE_GATE,
        )
    _note_dropped(context, dropped)
    enriched = payload.model_dump(exclude_none=True, exclude={"picks"})
    enriched["items"] = items
    return enriched


async def enrich_comparison(
    payload: PresentComparisonPayload, context: EnrichmentContext
) -> dict[str, Any]:
    dropped: list[str] = []
    entries = []
    for entry in payload.entries:
        product = context.state.seen_products.get(entry.product_id)
        if product is None:
            dropped.append(entry.product_id)
            continue
        entries.append(entry.model_dump(exclude_none=True) | {"product": _record(product)})
    if len(entries) < 2:
        raise PresentationRefused(
            "对比至少需要 2 个来自本次会话搜索结果的商品。",
            PROVENANCE_GATE,
        )
    _note_dropped(context, dropped)
    enriched = payload.model_dump(exclude_none=True)
    enriched["entries"] = entries
    if (delta := comparison_price_delta(entries)) is not None:
        enriched["price_delta"] = delta
    return enriched


async def enrich_plan(payload: PresentPlanPayload, context: EnrichmentContext) -> dict[str, Any]:
    dropped: list[str] = []
    enriched = payload.model_dump(exclude_none=True)
    enriched["steps"] = [
        {
            "label": step.label,
            "detail": step.detail,
            "products": _resolve(context.state, step.product_ids, dropped),
        }
        for step in payload.steps
    ]
    _note_dropped(context, dropped)
    return enriched


async def enrich_guide(payload: PresentGuidePayload, context: EnrichmentContext) -> dict[str, Any]:
    dropped: list[str] = []
    enriched = payload.model_dump(exclude_none=True, exclude={"related_product_ids"})
    enriched["related_products"] = _resolve(context.state, payload.related_product_ids, dropped)
    _note_dropped(context, dropped)
    return enriched


async def enrich_order_status(
    payload: PresentOrderStatusPayload, context: EnrichmentContext
) -> dict[str, Any]:
    order = await context.backend.get_order(context.session, payload.order_id)
    if order is None:
        raise PresentationRefused(f"没有找到订单 {payload.order_id}，请先查询。")
    enriched = payload.model_dump(exclude_none=True)
    enriched["order"] = order.model_dump(mode="json", exclude_none=True)
    return enriched


async def enrich_checkout(payload: CheckoutPayload, context: EnrichmentContext) -> dict[str, Any]:
    cart = await context.backend.get_cart(context.session)
    if not cart.items:
        raise PresentationRefused("购物车是空的，没有可结账的商品。")
    enriched = payload.model_dump(exclude_none=True)
    enriched["cart"] = cart_payload(cart)
    handoffs = await context.backend.checkout_handoff(context.session, cart)
    if handoffs:
        enriched["handoffs"] = [h.model_dump(exclude_none=True) for h in handoffs]
    return enriched


# ── 流式预览：调用还在流式传输中时的 payload ──────────────────


def _seen(state: ShoppingSessionState, product_id: Any) -> dict[str, Any] | None:
    product = state.seen_products.get(product_id) if isinstance(product_id, str) else None
    return None if product is None else _record(product)


def _seen_all(state: ShoppingSessionState, product_ids: Any) -> list[dict[str, Any]]:
    if not isinstance(product_ids, list):
        return []
    return [record for pid in product_ids if (record := _seen(state, pid)) is not None]


def partial_products(data: dict[str, Any], state: ShoppingSessionState) -> dict[str, Any]:
    items = []
    for pick in data.get("picks") or []:
        if isinstance(pick, dict) and (record := _seen(state, pick.get("product_id"))):
            item: dict[str, Any] = {"product": record}
            if pick.get("reason"):
                item["reason"] = pick["reason"]
            items.append(item)
    payload: dict[str, Any] = {"items": items}
    for key in ("title", "layout"):
        if data.get(key):
            payload[key] = data[key]
    return payload


def partial_plan(data: dict[str, Any], state: ShoppingSessionState) -> dict[str, Any]:
    steps = [
        {
            "label": step["label"],
            "detail": step.get("detail"),
            "products": _seen_all(state, step.get("product_ids")),
        }
        for step in data.get("steps") or []
        if isinstance(step, dict) and step.get("label")
    ]
    payload: dict[str, Any] = {"title": data.get("title") or "", "steps": steps}
    if data.get("intro"):
        payload["intro"] = data["intro"]
    return payload


def partial_comparison(data: dict[str, Any], state: ShoppingSessionState) -> dict[str, Any]:
    entries = []
    for entry in data.get("entries") or []:
        if isinstance(entry, dict) and (record := _seen(state, entry.get("product_id"))):
            entries.append(
                {
                    "product_id": entry.get("product_id"),
                    "pros": entry.get("pros") or [],
                    "cons": entry.get("cons") or [],
                    "best_for": entry.get("best_for"),
                    "product": record,
                }
            )
    payload: dict[str, Any] = {"entries": entries, "dimensions": data.get("dimensions") or []}
    for key in ("title", "recommended_product_id"):
        if data.get(key):
            payload[key] = data[key]
    return payload


def partial_guide(data: dict[str, Any], state: ShoppingSessionState) -> dict[str, Any] | None:
    del state  # 指南的 sections 是模型的文本，不需要会话数据拼接
    sections = [
        {"heading": section["heading"], "body": section["body"]}
        for section in data.get("sections") or []
        if isinstance(section, dict) and section.get("heading") and section.get("body")
    ]
    if not data.get("title") and not sections:
        return None
    return {"title": data.get("title") or "", "sections": sections}


# ── 组件注册表 ──────────────────────────────────────────────────────


def _component(name: str, component: str, model: type, enrich: Any = None, partial: Any = None):
    return PresentationComponent(
        name=name, component=component, payload_model=model, enrich=enrich, enrich_partial=partial
    )


PRESENTATION_COMPONENTS: dict[str, PresentationComponent] = {
    spec.name: spec
    for spec in (
        _component(
            "present_products",
            "products",
            PresentProductsPayload,
            enrich_products,
            partial_products,
        ),
        _component(
            "present_comparison",
            "comparison",
            PresentComparisonPayload,
            enrich_comparison,
            partial_comparison,
        ),
        _component("present_plan", "plan", PresentPlanPayload, enrich_plan, partial_plan),
        _component("present_guide", "guide", PresentGuidePayload, enrich_guide, partial_guide),
        _component(
            "present_order_status", "order_status", PresentOrderStatusPayload, enrich_order_status
        ),
        _component("checkout", "checkout", CheckoutPayload, enrich_checkout),
        _component(CHIPS_TOOL, CHIPS_COMPONENT, PresentSuggestionsPayload),
    )
}
