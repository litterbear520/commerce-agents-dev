"""商户的内置组件：指标卡按名字解析成本会话工具返回过的数值，摘要条目拼上它指向的
商品条目或变更记录，变更预览由暂存记录生成，并去掉模型文字里和记录矛盾的部分。每个组件
都有一个流式预览钩子，渲染还在流式输出的调用里已经有依据的部分。
"""
# 项目中对应 merchant-agent/core/merchant_agent/enrichment.py
# 省略：resolve_analysis_metric（Step 21）

from __future__ import annotations

import re
from datetime import date, datetime
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
    PREVIEW_TOOL,
    DigestItem,
    MetricPick,
    PresentChangePreviewPayload,
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
    """摘要条目：本会话工具返回过 ``ref_id`` 指向的商品条目或变更记录时，把记录附上。"""
    ref_id = str(ref_id or "")
    if ref_id in state.seen_listings:
        entry["listing"] = state.seen_listings[ref_id].model_dump(exclude_none=True)
    if ref_id in state.seen_changes:
        entry["change"] = state.seen_changes[ref_id].model_dump(mode="json", exclude_none=True)
    return entry


_DIGEST_KINDS = frozenset(get_args(DigestItem.model_fields["kind"].annotation))


def partial_digest(data: dict[str, Any], state: MerchantSessionState) -> dict[str, Any] | None:
    """还在流式输出的摘要里，kind 和 headline 都已完整的条目（schema 里没有的 kind 等到
    校验再说），每条拼上它的商品条目或变更记录。"""
    items = [
        _joined(dict(item), item.get("ref_id"), state)
        for item in data.get("items") or []
        if isinstance(item, dict) and item.get("kind") in _DIGEST_KINDS and item.get("headline")
    ]
    if not items and not data.get("title"):
        return None
    return {"title": data.get("title") or "", "items": items}


# ── present_change_preview ───────────────────────────────────────────

# 只有冲突才算数：这个符号对应的币种里没有一个是这条变更的币种。
_CURRENCY_SYMBOLS: dict[str, frozenset[str]] = {
    "$": frozenset({"USD", "CAD", "AUD", "NZD", "SGD", "HKD", "MXN"}),
    "€": frozenset({"EUR"}),
    "£": frozenset({"GBP"}),
    "¥": frozenset({"JPY", "CNY"}),
}

# 下面的星期、月份按英文缩写匹配模型文字，改成中文会改变匹配逻辑，所以保留英文
_MONTH_NUMBERS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
_WEEKDAYS_PATTERN = (
    r"mon(?:day)?|tue(?:s(?:day)?)?|wed(?:nesday)?|thu(?:r(?:s(?:day)?)?)?"
    r"|fri(?:day)?|sat(?:urday)?|sun(?:day)?"
)
_MONTHS_PATTERN = (
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?"
    r"|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
)
# 星期后面跟着日-月或月-日；单独一个星期没法核对。
# 只匹配完整的词，所以 "Wedding Jul 12" 不算周三。
_WEEKDAY_DATE = re.compile(
    rf"\b(?P<w>{_WEEKDAYS_PATTERN})\b\.?,?\s+"
    rf"(?:(?P<d1>\d{{1,2}})\s+(?P<m1>{_MONTHS_PATTERN})\b"
    rf"|(?P<m2>{_MONTHS_PATTERN})\b\.?\s+(?P<d2>\d{{1,2}}))\b",
    re.IGNORECASE,
)
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_WEEKDAY_INDEX = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def _drop_fields(enriched: dict[str, Any], offending: Any) -> list[str]:
    return [
        name
        for name in ("headline", "note")
        if isinstance(text := enriched.get(name), str)
        and offending(text)
        and enriched.pop(name, None) is not None
    ]


def reconcile_change_preview_currency(enriched: dict[str, Any]) -> str | None:
    """去掉货币符号和这条变更的币种冲突的模型文字；去掉了东西时，返回给模型的说明。"""
    change = enriched.get("change")
    currency = change.get("currency") if isinstance(change, dict) else None
    if not currency:
        return None
    conflicting = tuple(sym for sym, codes in _CURRENCY_SYMBOLS.items() if currency not in codes)
    dropped = _drop_fields(enriched, lambda text: any(sym in text for sym in conflicting))
    if not dropped:
        return None
    return (
        f"去掉了 {' 和 '.join(dropped)}：这张卡上的金额必须用这条变更的币种（{currency}）表示。"
        "用暂存变更记录自己的数字重新表述。"
    )


def _candidate_years(change: dict[str, Any]) -> list[int]:
    """这条变更自己的日期里出现的年份；没有的话，取暂存那一年和下一年，因为十二月暂存
    的时间窗口可能从一月开始。"""
    corpus = [str(change.get("summary", ""))]
    for item in change.get("items") or []:
        if isinstance(item, dict):
            corpus.extend(str(v) for v in (item.get("before"), item.get("after")) if v)
    years = {int(m.group(1)) for text in corpus for m in _ISO_DATE.finditer(text)}
    if not years:
        created = str(change.get("created_at", ""))
        try:
            year = datetime.fromisoformat(created.replace("Z", "+00:00")).year
        except ValueError:
            return []
        years = {year, year + 1}
    return sorted(years)


def reconcile_change_preview_weekdays(enriched: dict[str, Any]) -> str | None:
    """去掉把星期和日期配错的模型文字：这个日期在变更日期涉及的任何一年里都不是那个
    星期；去掉了东西时，返回给模型的说明。"""
    change = enriched.get("change")
    if not isinstance(change, dict):
        return None
    years = _candidate_years(change)
    if not years:
        return None

    def has_wrong_weekday(text: str) -> bool:
        for match in _WEEKDAY_DATE.finditer(text):
            weekday = _WEEKDAY_INDEX[match.group("w").lower()[:3]]
            month = _MONTH_NUMBERS[(match.group("m1") or match.group("m2")).lower()[:3]]
            day = int(match.group("d1") or match.group("d2"))
            plausible = False
            for year in years:
                try:
                    plausible = date(year, month, day).weekday() == weekday
                except ValueError:
                    continue
                if plausible:
                    break
            if not plausible:
                return True
        return False

    dropped = _drop_fields(enriched, has_wrong_weekday)
    if not dropped:
        return None
    return (
        f"去掉了 {' 和 '.join(dropped)}：里面写的星期和它的日期对不上。按暂存变更记录自己的"
        "日期推出星期再重新表述，或者只写日期、不写星期。"
    )


async def enrich_change_preview(
    payload: PresentChangePreviewPayload, context: EnrichmentContext
) -> dict[str, Any]:
    change = context.state.seen_changes.get(payload.change_id)
    if change is None:
        raise PresentationRefused(
            "这个 change_id 不是本次会话暂存过或列出过的。先暂存这条变更，再预览它。"
        )
    enriched = payload.model_dump(exclude_none=True)
    enriched["change"] = change.model_dump(mode="json", exclude_none=True)
    for reconcile in (reconcile_change_preview_currency, reconcile_change_preview_weekdays):
        if note := reconcile(enriched):
            context.notes.append(note)
    return enriched


def partial_change_preview(
    data: dict[str, Any], state: MerchantSessionState
) -> dict[str, Any] | None:
    """change_id 一完整就给出暂存记录；模型的 headline 和 note 等到最终事件才加上，那时
    核对函数已经读过它们。"""
    change = state.seen_changes.get(str(data.get("change_id") or ""))
    if change is None:
        return None
    return {
        "change_id": change.change_id,
        "change": change.model_dump(mode="json", exclude_none=True),
    }


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
            name=PREVIEW_TOOL,
            component="change_preview",
            payload_model=PresentChangePreviewPayload,
            enrich=enrich_change_preview,
            enrich_partial=partial_change_preview,
        ),
        PresentationComponent(
            name=CHIPS_TOOL,
            component=CHIPS_COMPONENT,
            payload_model=PresentSuggestionsPayload,
        ),
    )
}
