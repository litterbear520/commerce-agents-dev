# 项目中对应 merchant-agent/core/tests/test_presentation.py
# 省略：变更预览的 payload 校验、币种核对、星期核对（Step 20）

import pytest
from pydantic import ValidationError

from merchant_agent.tools.presentation import (
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
