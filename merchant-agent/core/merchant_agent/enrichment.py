"""商户的内置组件：指标卡按名字解析成本会话工具返回过的数值，摘要条目拼上它指向的
商品条目记录。每个组件都有一个流式预览钩子，渲染还在流式输出的调用里已经有依据的部分。
"""
# 项目中对应 merchant-agent/core/merchant_agent/enrichment.py
# 省略：resolve_analysis_metric（Step 21）；变更预览及其币种、星期核对，
# 以及摘要条目拼接变更记录（Step 20）

from __future__ import annotations

from typing import Any, get_args

from commerce_common.presentation import (
    CHIPS_COMPONENT,
    CHIPS_TOOL,
    EnrichmentContext,
    PresentationComponent,
    PresentationRefused,
    PresentSuggestionsPayload,
)

from .tools.presentation import (
    DigestItem,
    MetricPick,
    PresentDigestPayload,
    PresentMetricsPayload,
)
from .types import MerchantSessionState

# ── present_metrics ──────────────────────────────────────────────────

# 简写：只有按本会话已有的名字都解析不到时才尝试。
_METRIC_ALIASES: dict[str, str] = {
    "conversion": "conversion_rate",
    "cvr": "conversion_rate",
    "aov": "average_order_value",
    "avg_order_value": "average_order_value",
    "average_order": "average_order_value",
    "revenue": "sales",
}


def resolve_campaign_metric(state: MerchantSessionState, pick: str) -> dict[str, Any] | None:
    """指名一个见过的营销活动（按 id 或名称）加 spend、revenue、budget、roas 之一的
    指标；匹配到多个活动时取最长的那个。"""
    # 度量词保持英文：它们是匹配用的关键字，工具描述也要求按这个写法填
    text = pick.lower()
    matches = [
        (len(token), campaign)
        for campaign in state.seen_campaigns.values()
        for token in (campaign.campaign_id.lower(), campaign.name.lower())
        if token in text
    ]
    if not matches:
        return None
    campaign = max(matches, key=lambda match: match[0])[1]
    currency: str | None = campaign.currency
    value: float | None
    if "roas" in text or "return on ad spend" in text:
        measure = "roas"
        value = (
            round(campaign.revenue / campaign.spend, 2)
            if campaign.spend and campaign.revenue is not None
            else None
        )
        currency = None
    elif "revenue" in text:
        measure, value = "revenue", campaign.revenue
    elif "budget" in text:
        measure, value = "budget", campaign.budget
    elif "spend" in text or "spent" in text:
        measure, value = "spend", campaign.spend
    else:
        return None
    if value is None:
        return None
    return {
        "metric": f"{campaign.name} — {measure}",
        "value": value,
        "change_pct": None,
        "currency": currency,
    }


def resolve_metrics(
    state: MerchantSessionState, picks: list[MetricPick]
) -> tuple[list[dict[str, Any]], list[str]]:
    """每个指标解析成一张卡：来自快照、查询过的序列或营销活动；另外返回本会话哪里都
    给不出的指标。"""
    snapshot = state.latest_snapshot
    snapshot_values: dict[str, tuple[float | None, float | None]] = {}
    if snapshot is not None:
        snapshot_values = {
            "sales": (snapshot.sales, snapshot.sales_change_pct),
            "orders": (float(snapshot.orders), snapshot.orders_change_pct),
            "traffic": (snapshot.traffic, snapshot.traffic_change_pct),
            "conversion_rate": (snapshot.conversion_rate, snapshot.conversion_change_pct),
            "average_order_value": (snapshot.average_order_value, None),
        }
    resolved: list[dict[str, Any]] = []
    missing: list[str] = []
    for pick in picks:
        key = pick.metric.strip().lower().replace(" ", "_")
        series = state.seen_series.get(pick.metric) or state.seen_series.get(key)
        campaign = resolve_campaign_metric(state, pick.metric)
        if key not in snapshot_values and series is None and campaign is None:
            key = _METRIC_ALIASES.get(key, key)
        if key in snapshot_values and snapshot_values[key][0] is not None:
            value, change_pct = snapshot_values[key]
            resolved.append(
                {
                    "metric": key,
                    "value": value,
                    "change_pct": change_pct,
                    "note": pick.note,
                    "currency": snapshot.currency if snapshot else None,
                }
            )
        elif series is not None and not series.points:
            missing.append(pick.metric)
        elif series is not None:
            resolved.append(
                {
                    "metric": series.metric,
                    "series": series.model_dump(mode="json", exclude_none=True),
                    "note": pick.note,
                }
            )
        elif campaign is not None:
            resolved.append(campaign | {"note": pick.note})
        else:
            missing.append(pick.metric)
    return resolved, missing


async def enrich_metrics(
    payload: PresentMetricsPayload, context: EnrichmentContext
) -> dict[str, Any]:
    state: MerchantSessionState = context.state
    metrics, missing = resolve_metrics(state, payload.picks)
    if not metrics:
        raise PresentationRefused(
            "这些指标都不是本会话工具返回过的度量（快照里的数字、查询过的序列或营销活动）。"
            "先读取数据（get_business_snapshot、query_metrics、get_campaign_performance），"
            "再按工具的写法给每个指标命名，或者写成营销活动 id 加一个度量（'<campaign_id> spend'）。"
        )
    if missing:
        context.notes.append(f"跳过了本会话没有返回过的指标：{'、'.join(missing)}。")
    enriched = payload.model_dump(exclude_none=True, exclude={"picks"})
    enriched["metrics"] = metrics
    _snapshot_period(enriched, state)
    return enriched


def _snapshot_period(payload: dict[str, Any], state: MerchantSessionState) -> None:
    if state.latest_snapshot is not None and not payload.get("period"):
        payload["period"] = state.latest_snapshot.period


def partial_metrics(data: dict[str, Any], state: MerchantSessionState) -> dict[str, Any] | None:
    """还在流式输出的调用里已经有依据的指标卡；在第一个指标解析出来之前什么都不出，
    这样被拒绝的调用不会先冒出一张卡。"""
    picks = [
        MetricPick.model_construct(metric=pick["metric"], note=pick.get("note"))
        for pick in data.get("picks") or []
        if isinstance(pick, dict) and isinstance(pick.get("metric"), str) and pick["metric"]
    ]
    metrics, _missing = resolve_metrics(state, picks)
    if not metrics:
        return None
    payload: dict[str, Any] = {"metrics": metrics}
    for key in ("title", "period"):
        if data.get(key):
            payload[key] = data[key]
    _snapshot_period(payload, state)
    return payload


# ── present_digest ───────────────────────────────────────────────────


async def enrich_digest(
    payload: PresentDigestPayload, context: EnrichmentContext
) -> dict[str, Any]:
    enriched = payload.model_dump(exclude_none=True)
    enriched["items"] = [
        _joined(item.model_dump(exclude_none=True), item.ref_id, context.state)
        for item in payload.items
    ]
    return enriched


def _joined(entry: dict[str, Any], ref_id: Any, state: MerchantSessionState) -> dict[str, Any]:
    """摘要条目：本会话工具返回过 ``ref_id`` 指向的商品条目记录时，把记录附上。"""
    # 项目中还会附上变更记录（seen_changes），Step 20 再加
    ref_id = str(ref_id or "")
    if ref_id in state.seen_listings:
        entry["listing"] = state.seen_listings[ref_id].model_dump(exclude_none=True)
    return entry


_DIGEST_KINDS = frozenset(get_args(DigestItem.model_fields["kind"].annotation))


def partial_digest(data: dict[str, Any], state: MerchantSessionState) -> dict[str, Any] | None:
    """还在流式输出的摘要里，kind 和 headline 都已完整的条目（schema 里没有的 kind 等到
    校验再说），每条拼上它的商品条目记录。"""
    items = [
        _joined(dict(item), item.get("ref_id"), state)
        for item in data.get("items") or []
        if isinstance(item, dict) and item.get("kind") in _DIGEST_KINDS and item.get("headline")
    ]
    if not items and not data.get("title"):
        return None
    return {"title": data.get("title") or "", "items": items}


PRESENTATION_COMPONENTS: dict[str, PresentationComponent] = {
    spec.name: spec
    for spec in (
        PresentationComponent(
            name="present_metrics",
            component="metrics",
            payload_model=PresentMetricsPayload,
            enrich=enrich_metrics,
            enrich_partial=partial_metrics,
        ),
        PresentationComponent(
            name="present_digest",
            component="digest",
            payload_model=PresentDigestPayload,
            enrich=enrich_digest,
            enrich_partial=partial_digest,
        ),
        PresentationComponent(
            name=CHIPS_TOOL,
            component=CHIPS_COMPONENT,
            payload_model=PresentSuggestionsPayload,
        ),
    )
}
