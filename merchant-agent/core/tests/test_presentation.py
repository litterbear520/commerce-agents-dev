# 项目中对应 merchant-agent/core/tests/test_presentation.py

import pytest
from pydantic import ValidationError

from merchant_agent.enrichment import (
    reconcile_change_preview_currency,
    reconcile_change_preview_weekdays,
)
from merchant_agent.tools.presentation import (
    PresentChangePreviewPayload,
    PresentDigestPayload,
    PresentMetricsPayload,
)


def test_metrics_payload_validates_picks_and_drops_undeclared_keys():
    payload = PresentMetricsPayload.model_validate(
        {
            "title": "上周概览",
            "period": "last_7_days",
            "picks": [{"metric": "sales", "note": "比前一周高"}],
            "suggestions": ["按品类拆分销售额", "按天看转化率"],
        }
    )
    assert payload.picks[0].metric == "sales"
    assert "suggestions" not in payload.model_dump()
    with pytest.raises(ValidationError):
        PresentMetricsPayload.model_validate({"picks": []})


def test_metric_shorthand_resolves_to_canonical_snapshot_values():
    from merchant_agent.enrichment import resolve_metrics
    from merchant_agent.types import BusinessSnapshot, MerchantSessionState

    state = MerchantSessionState()
    state.remember_snapshot(
        BusinessSnapshot(
            period="last_7_days",
            sales=17338.0,
            orders=386,
            traffic=9120,
            conversion_rate=2.9,
            average_order_value=44.92,
        )
    )
    payload = PresentMetricsPayload.model_validate(
        {
            "picks": [
                {"metric": "conversion"},  # conversion_rate 的简写
                {"metric": "AOV"},  # average_order_value 的简写
                {"metric": "revenue"},  # sales 的简写
                {"metric": "made-up-metric"},  # 快照里没有这个字段
            ]
        }
    )
    resolved, missing = resolve_metrics(state, payload.picks)
    by_metric = {entry["metric"]: entry for entry in resolved}
    assert by_metric["conversion_rate"]["value"] == 2.9
    assert by_metric["average_order_value"]["value"] == 44.92
    assert by_metric["sales"]["value"] == 17338.0
    assert missing == ["made-up-metric"]


def test_a_figure_the_store_cannot_supply_is_a_missing_pick_not_a_zero_tile():
    from merchant_agent.enrichment import resolve_campaign_metric, resolve_metrics
    from merchant_agent.types import BusinessSnapshot, Campaign, MerchantSessionState, MetricSeries

    state = MerchantSessionState()
    # 没有分析权限：流量和转化率是 None，note 说明原因。
    state.remember_snapshot(
        BusinessSnapshot(
            period="last_7_days",
            sales=17338.0,
            orders=386,
            note="流量和转化率需要分析权限，这家店还没有授权",
        )
    )
    state.remember_series(MetricSeries(metric="sessions", note="历史只保留 60 天"))
    state.remember_campaigns(
        [Campaign(campaign_id="c-1", name="春季推广", status="active", budget=500.0)]
    )
    payload = PresentMetricsPayload.model_validate(
        {
            "picks": [
                {"metric": "sales"},
                {"metric": "traffic"},
                {"metric": "conversion"},
                {"metric": "sessions"},
            ]
        }
    )
    resolved, missing = resolve_metrics(state, payload.picks)
    assert [entry["metric"] for entry in resolved] == ["sales"]
    assert missing == ["traffic", "conversion", "sessions"]
    # 渠道不报告花费和收入时，也不会出 ROAS 指标卡。
    assert resolve_campaign_metric(state, "春季推广 roas") is None
    assert resolve_campaign_metric(state, "春季推广 budget")["value"] == 500.0


def test_metric_alias_never_shadows_a_series_seen_under_the_raw_name():
    from merchant_agent.enrichment import resolve_metrics
    from merchant_agent.types import BusinessSnapshot, MerchantSessionState, MetricSeries

    state = MerchantSessionState()
    state.remember_snapshot(
        BusinessSnapshot(
            period="last_7_days",
            sales=17338.0,
            orders=386,
            traffic=9120,
            conversion_rate=2.9,
            average_order_value=44.92,
        )
    )
    state.remember_series(
        MetricSeries(
            metric="revenue",
            period="last_30_days",
            granularity="day",
            points=[{"date": "2026-07-01", "value": 2100.0}],
        )
    )
    payload = PresentMetricsPayload.model_validate({"picks": [{"metric": "revenue"}]})
    resolved, missing = resolve_metrics(state, payload.picks)
    assert missing == []
    (entry,) = resolved
    assert entry["metric"] == "revenue"
    assert entry["series"]["period"] == "last_30_days"
    assert "value" not in entry


def test_digest_payload_requires_kind_and_headline():
    payload = PresentDigestPayload.model_validate(
        {
            "items": [
                {
                    "kind": "low_stock",
                    "ref_id": "L-001",
                    "headline": "两款儿童房花盆快断货了",
                    "why_it_matters": "上周卖了 41 件",
                }
            ]
        }
    )
    assert payload.items[0].kind == "low_stock"
    with pytest.raises(ValidationError):
        PresentDigestPayload.model_validate({"items": [{"headline": "缺少 kind"}]})


def test_change_preview_payload_requires_change_id():
    payload = PresentChangePreviewPayload.model_validate(
        {"change_id": "chg-0001", "headline": "补货 24 个花盆"}
    )
    assert payload.change_id == "chg-0001"
    with pytest.raises(ValidationError):
        PresentChangePreviewPayload.model_validate({"headline": "没有 change id"})


def test_change_preview_currency_reconciliation_drops_conflicting_text():
    enriched = {
        "change_id": "chg-0002",
        "headline": "下调房价：$204 降到 $183.60",
        "note": "每晚房价从 €204 降到 €183.60（整个时段少收 €889）。",
        "change": {"change_id": "chg-0002", "currency": "USD"},
    }
    message = reconcile_change_preview_currency(enriched)
    assert message is not None and "USD" in message
    assert "note" not in enriched
    assert enriched["headline"] == "下调房价：$204 降到 $183.60"


def test_change_preview_currency_reconciliation_is_a_no_op_when_consistent():
    enriched = {
        "change_id": "chg-0003",
        "note": "毛利率从 56.2% 降到 53.9%（$24.00 → $22.80）。",
        "change": {"change_id": "chg-0003", "currency": "USD"},
    }
    assert reconcile_change_preview_currency(enriched) is None
    assert "note" in enriched
    dollar_elsewhere = {"note": "$24.00 → $22.80", "change": {"change_id": "c", "currency": "CAD"}}
    assert reconcile_change_preview_currency(dollar_elsewhere) is None
    assert "note" in dollar_elsewhere
    no_currency = {"note": "立减 €10", "change": {"change_id": "chg-0004"}}
    assert reconcile_change_preview_currency(no_currency) is None
    assert "note" in no_currency


# 星期核对按英文的星期、月份写法匹配，所以下面几个测试里模型写的文字保留英文。
# 2026-07-11 是周六，2026-07-12 是周日，2026-07-13 是周一。
_PROMO_CHANGE = {
    "change_id": "chg-0006",
    "summary": "周末促销（85 折，2026-07-11 至 2026-07-13）",
    "items": [{"target": "AR-2102", "field": "promotion_price", "before": 24.0, "after": 20.4}],
    "created_at": "2026-07-10T09:06:29Z",
}


def test_change_preview_weekday_reconciliation_drops_mismatched_text():
    enriched = {
        "headline": "Weekend Promo: 15% off — Sat 12 Jul & Sun 13 Jul",
        "note": "Runs Saturday and Sunday only.",
        "change": dict(_PROMO_CHANGE),
    }
    message = reconcile_change_preview_weekdays(enriched)
    assert message is not None and "headline" in message
    assert "headline" not in enriched
    # 没带日期的星期不做核对。
    assert enriched["note"] == "Runs Saturday and Sunday only."


def test_change_preview_weekday_reconciliation_keeps_correct_pairs():
    enriched = {
        "headline": "Weekend Promo: 15% off — Sat 11 Jul & Sun 12 Jul",
        "note": "Ends Monday, Jul 13.",
        "change": dict(_PROMO_CHANGE),
    }
    assert reconcile_change_preview_weekdays(enriched) is None
    assert enriched["headline"].startswith("Weekend Promo")


def test_change_preview_weekday_reconciliation_uses_created_at_year_when_no_dates():
    dateless = {
        "change_id": "chg-0007",
        "summary": "更新标题",
        "items": [{"target": "AR-2102", "field": "title", "before": "a", "after": "b"}],
        "created_at": "2026-07-10T09:06:29Z",
    }
    wrong = {"headline": "Ready for Sat 12 Jul", "change": dict(dateless)}
    assert reconcile_change_preview_weekdays(wrong) is not None
    right = {"headline": "Ready for Sun 12 Jul", "change": dict(dateless)}
    assert reconcile_change_preview_weekdays(right) is None
    # 没有变更记录、或 created_at 解析不出来时，没有可以对照的东西。
    assert reconcile_change_preview_weekdays({"headline": "Sat 12 Jul"}) is None
    assert (
        reconcile_change_preview_weekdays(
            {"headline": "Sat 12 Jul", "change": {"summary": "x", "created_at": "unknown"}}
        )
        is None
    )


def test_change_preview_weekday_reconciliation_matches_whole_words_only():
    # "Wedding" 不是星期；月份的完整写法也能解析。
    enriched = {
        "headline": "Wedding Jul 11 party bundle",
        "note": "Runs Saturday, July 11 through Sunday, July 12.",
        "change": dict(_PROMO_CHANGE),
    }
    assert reconcile_change_preview_weekdays(enriched) is None
    wrong_full = {"note": "Starts Saturday, July 12.", "change": dict(_PROMO_CHANGE)}
    assert reconcile_change_preview_weekdays(wrong_full) is not None
    assert "note" not in wrong_full
