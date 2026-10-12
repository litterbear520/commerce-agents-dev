# 项目中对应 merchant-agent/core/tests/test_changes.py

import pytest

from merchant_agent import (
    ActorKind,
    ChangeItem,
    ChangeKind,
    ChangeLedger,
    ChangeNotApplicable,
    ChangeStatus,
    GuardrailViolation,
)
from merchant_agent.changes import check_guardrails


def _price_items(count: int, before: float = 100.0, after: float = 110.0) -> list[ChangeItem]:
    return [
        ChangeItem(target=f"L-{i:03d}", field="price", before=before, after=after)
        for i in range(count)
    ]


@pytest.fixture
def rate_config(config):
    """把 nightly_rate 同时加进定价字段和商品信息修改要拦下的字段后的配置。"""
    return config.model_copy(
        update={
            "price_bearing_fields": config.price_bearing_fields + ("nightly_rate",),
            "listing_update_blocked_fields": config.listing_update_blocked_fields
            + ("nightly_rate",),
        }
    )


# ── 护栏检查 ──────────────────────────────────────────────────────────────────


def test_within_guardrails_is_clean(config):
    assert check_guardrails(ChangeKind.PRICE_UPDATE, _price_items(3), config) == []


def test_bulk_cap_violation(config):
    violations = check_guardrails(
        ChangeKind.PRICE_UPDATE, _price_items(config.max_items_per_change + 1), config
    )
    assert any("上限是每次" in v and "拆成" in v for v in violations)


def test_price_delta_violation_names_the_listing(config):
    items = [ChangeItem(target="L-001", field="price", before=100.0, after=160.0)]
    violations = check_guardrails(ChangeKind.PRICE_UPDATE, items, config)
    assert len(violations) == 1
    assert "L-001" in violations[0]
    assert "20%" in violations[0]


def test_price_delta_applies_to_decreases_too(config):
    items = [ChangeItem(target="L-001", field="price", before=100.0, after=50.0)]
    assert check_guardrails(ChangeKind.PRICE_UPDATE, items, config)


def test_price_bearing_fields_are_delta_checked_in_any_kind(config):
    # 200 -> 140 变动 30%，超过 20% 的改价上限；200 -> 80 变动 60%，超过 50% 的促销上限。
    items = [ChangeItem(target="L-001", field="price", before=200.0, after=140.0)]
    violations = check_guardrails(ChangeKind.PRICE_UPDATE, items, config)
    assert any("30%" in v for v in violations)
    deep = [ChangeItem(target="L-001", field="price", before=200.0, after=80.0)]
    assert any("促销上限" in v for v in check_guardrails(ChangeKind.PROMOTION, deep, config))


def test_extended_price_bearing_field_is_delta_checked(config, rate_config):
    # 默认配置里只有 "price" 是定价字段。
    items = [ChangeItem(target="L-001", field="nightly_rate", before=200.0, after=140.0)]
    assert check_guardrails(ChangeKind.PRICE_UPDATE, items, config) == []
    violations = check_guardrails(ChangeKind.PRICE_UPDATE, items, rate_config)
    assert any("30%" in v for v in violations)
    priced = [ChangeItem(target="L-002", field="price", before=200.0, after=140.0)]
    assert check_guardrails(ChangeKind.PRICE_UPDATE, priced, rate_config)
    deep = [ChangeItem(target="L-001", field="nightly_rate", before=200.0, after=80.0)]
    assert any("促销上限" in v for v in check_guardrails(ChangeKind.PROMOTION, deep, rate_config))


def test_promotion_items_are_price_moves_whatever_the_field_is_called(config):
    deep = [ChangeItem(target="L-001", field="promotion_price", before=100.0, after=20.0)]
    assert any("促销上限" in v for v in check_guardrails(ChangeKind.PROMOTION, deep, config))
    within = [ChangeItem(target="L-001", field="promotion_price", before=100.0, after=70.0)]
    assert check_guardrails(ChangeKind.PROMOTION, within, config) == []


def test_promotion_depth_uses_its_own_cap_not_the_price_cap(config):
    # 200 -> 140 是 30% 的折扣，在 50% 的促销上限以内，超过 20% 的改价上限。
    within = [ChangeItem(target="L-001", field="price", before=200.0, after=140.0)]
    assert check_guardrails(ChangeKind.PROMOTION, within, config) == []
    over = [ChangeItem(target="L-001", field="price", before=200.0, after=80.0)]
    violations = check_guardrails(ChangeKind.PROMOTION, over, config)
    assert any("促销上限" in v for v in violations)


def test_zero_or_missing_price_is_refused(config):
    zeroed = [ChangeItem(target="L-001", field="price", before=100.0, after=0)]
    violations = check_guardrails(ChangeKind.PRICE_UPDATE, zeroed, config)
    assert any("必须是正数" in v for v in violations)

    missing = [ChangeItem(target="L-002", field="price", before=100.0, after=None)]
    assert check_guardrails(ChangeKind.PRICE_UPDATE, missing, config)


@pytest.mark.parametrize("before", [None, 0, -5.0, "not-a-price"])
def test_price_move_without_grounded_before_is_refused(config, before):
    items = [ChangeItem(target="L-001", field="price", before=before, after=45.0)]
    violations = check_guardrails(ChangeKind.PRICE_UPDATE, items, config)
    assert any("没有可依据的当前价格" in v for v in violations)
    assert any("L-001" in v for v in violations)


def test_promotion_rate_move_without_grounded_before_is_refused(rate_config):
    items = [ChangeItem(target="L-410", field="nightly_rate", before=None, after=120.0)]
    violations = check_guardrails(ChangeKind.PROMOTION, items, rate_config)
    assert any("没有可依据的当前价格" in v for v in violations)


def test_non_price_fields_are_not_delta_checked(config):
    items = [ChangeItem(target="L-001", field="title", before="旧标题", after="新标题")]
    assert check_guardrails(ChangeKind.LISTING_UPDATE, items, config) == []


def test_protected_field_violation(config):
    items = [ChangeItem(target="L-001", field="tax_category", before="standard", after="exempt")]
    violations = check_guardrails(ChangeKind.LISTING_UPDATE, items, config)
    assert any("受保护" in v for v in violations)


def test_protected_fields_match_case_insensitively(config):
    items = [ChangeItem(target="L-001", field="Tax_Category", before="a", after="b")]
    violations = check_guardrails(ChangeKind.LISTING_UPDATE, items, config)
    assert any("受保护" in v for v in violations)


def test_listing_update_cannot_carry_price_or_stock(config):
    for field, after in (("price", 1.0), ("stock", 900), ("Price", 5.0)):
        items = [ChangeItem(target="L-001", field=field, before=None, after=after)]
        violations = check_guardrails(ChangeKind.LISTING_UPDATE, items, config)
        assert violations, f"{field} 通过商品信息修改溜了过去"


def test_listing_update_blocks_extended_rate_field_only_when_configured(config, rate_config):
    items = [ChangeItem(target="L-001", field="nightly_rate", before=None, after=95.0)]
    assert check_guardrails(ChangeKind.LISTING_UPDATE, items, config) == []
    violations = check_guardrails(ChangeKind.LISTING_UPDATE, items, rate_config)
    assert any("不能放在商品信息修改里改" in v for v in violations)


def test_restock_quantity_cap(config):
    over = config.max_restock_quantity + 10
    items = [ChangeItem(target="L-001", field="stock", before=3, after=3 + over)]
    violations = check_guardrails(ChangeKind.INVENTORY_ACTION, items, config)
    assert any("件的上限" in v for v in violations)
    within = [ChangeItem(target="L-001", field="stock", before=3, after=53)]
    assert check_guardrails(ChangeKind.INVENTORY_ACTION, within, config) == []


def test_restock_cap_follows_the_numbers_not_the_field_name(config):
    over = config.max_restock_quantity + 10
    items = [ChangeItem(target="AL-STAY-101", field="rooms", before=3, after=3 + over)]
    violations = check_guardrails(ChangeKind.INVENTORY_ACTION, items, config)
    assert any("件的上限" in v for v in violations)


def test_a_target_repeated_within_a_change_is_refused(config):
    # 每一行都在补货上限以内，合起来却超了；而且预览卡会让每一行都从同一个起始库存算起。
    within = config.max_restock_quantity
    items = [ChangeItem(target="L-001", field="stock", before=3, after=3 + within)] * 3
    violations = check_guardrails(ChangeKind.INVENTORY_ACTION, items, config)
    assert len(violations) == 2 and all("不止一次" in v for v in violations)
    two_fields = [
        ChangeItem(target="L-001", field="title", before="a", after="b"),
        ChangeItem(target="L-001", field="Description", before="a", after="b"),
        ChangeItem(target="L-002", field="title", before="a", after="b"),
    ]
    assert check_guardrails(ChangeKind.LISTING_UPDATE, two_fields, config) == []
    same_field_twice = two_fields + [ChangeItem(target="L-001", field="TITLE", after="c")]
    assert len(check_guardrails(ChangeKind.LISTING_UPDATE, same_field_twice, config)) == 1


def test_campaign_budget_cap(config):
    over = [
        ChangeItem(
            target="camp-1", field="budget", before=None, after=config.max_campaign_budget * 2
        )
    ]
    violations = check_guardrails(ChangeKind.CAMPAIGN, over, config)
    assert any("营销预算" in v for v in violations)
    within = [ChangeItem(target="camp-1", field="budget", before=None, after=500)]
    assert check_guardrails(ChangeKind.CAMPAIGN, within, config) == []


# ── 台账 ──────────────────────────────────────────────────────────────────────


def test_stage_records_actor_and_starts_staged(config):
    ledger = ChangeLedger(config)
    change = ledger.stage(
        kind=ChangeKind.INVENTORY_ACTION,
        summary="给两款儿童房花盆补货",
        items=[ChangeItem(target="L-001", field="stock", before=2, after=26)],
        actor="demo-operator",
    )
    assert change.status is ChangeStatus.STAGED
    assert change.created_by == "demo-operator"
    assert change.created_by_kind is ActorKind.OPERATOR
    assert change.applied_at is None
    assert ledger.pending() == [change]
    assert ledger.applied() == []


def test_agent_staged_change_keeps_the_operator_principal(config):
    ledger = ChangeLedger(config)
    change = ledger.stage(
        kind=ChangeKind.INVENTORY_ACTION,
        summary="给两款儿童房花盆补货",
        items=[ChangeItem(target="L-001", field="stock", before=2, after=26)],
        actor="demo-operator",
        actor_kind=ActorKind.AGENT,
    )
    assert change.created_by == "demo-operator"
    assert change.created_by_kind is ActorKind.AGENT

    applied = ledger.apply(change.change_id, actor="demo-operator")
    assert applied.applied_by == "demo-operator"
    assert applied.created_by_kind is ActorKind.AGENT


def test_stage_persists_backend_computed_money_fields(config):
    ledger = ChangeLedger(config)
    change = ledger.stage(
        kind=ChangeKind.PRICE_UPDATE,
        summary="L-001 降价 5%",
        items=[ChangeItem(target="L-001", field="price", before=24.0, after=22.8)],
        actor="demo-operator",
        currency="USD",
        margin_impact=-14.56,
        margin_before_pct=56.2,
        margin_after_pct=53.9,
    )
    assert change.currency == "USD"
    assert change.margin_before_pct == 56.2
    assert change.margin_after_pct == 53.9
    plain = ledger.stage(
        kind=ChangeKind.INVENTORY_ACTION,
        summary="补货",
        items=[ChangeItem(target="L-001", field="stock", before=2, after=26)],
        actor="demo-operator",
    )
    dumped = plain.model_dump(exclude_none=True)
    assert "currency" not in dumped and "margin_before_pct" not in dumped


def test_stage_refuses_guardrail_violations(config):
    ledger = ChangeLedger(config)
    with pytest.raises(GuardrailViolation) as excinfo:
        ledger.stage(
            kind=ChangeKind.PRICE_UPDATE,
            summary="全部重新定价",
            items=_price_items(config.max_items_per_change + 5),
            actor="demo-operator",
        )
    assert excinfo.value.violations
    assert ledger.pending() == []


def test_change_ids_are_distinct_and_sequential(config):
    ledger = ChangeLedger(config)
    first = ledger.stage(
        kind=ChangeKind.PROMOTION,
        summary="海洋房系列周末促销",
        items=[ChangeItem(target="L-001", field="promotion_price", before=40.0, after=34.0)],
        actor="demo-operator",
    )
    second = ledger.stage(
        kind=ChangeKind.CAMPAIGN,
        summary="起草返校季营销活动",
        items=[ChangeItem(target="campaign-draft", field="budget", before=None, after=500)],
        actor="demo-operator",
    )
    assert first.change_id != second.change_id
    assert len(ledger.pending()) == 2


def test_verbose_summary_trims_at_a_word_boundary_with_ellipsis(config):
    """摘要上限以省略号结尾；[truncated] 是清洗器的标记。"""
    # 截断按空格找词边界，所以语料保留英文
    ledger = ChangeLedger(config)
    change = ledger.stage(
        kind=ChangeKind.LISTING_UPDATE,
        summary="Refresh the listing copy " * 20,
        items=[ChangeItem(target="L-001", field="short_description", before="a", after="b")],
        actor="demo-operator",
    )
    assert len(change.summary) <= 200
    assert change.summary.endswith("…")
    assert "[truncated]" not in change.summary
    # 保留的文字是原文的前缀，原文紧接着的下一个字符是空格。
    trimmed = change.summary.removesuffix("…")
    original = "Refresh the listing copy " * 20
    assert original.startswith(trimmed)
    assert original[len(trimmed)] == " "


def test_apply_requires_a_staged_change_and_stamps_the_actor(config):
    ledger = ChangeLedger(config)
    change = ledger.stage(
        kind=ChangeKind.PRICE_UPDATE,
        summary="滞销款降价 10%",
        items=_price_items(1, before=100.0, after=90.0),
        actor="demo-operator",
    )
    applied = ledger.apply(change.change_id, actor="demo-operator")
    assert applied.status is ChangeStatus.APPLIED
    assert applied.applied_by == "demo-operator"
    assert applied.applied_at is not None
    assert ledger.pending() == []
    assert ledger.applied() == [applied]

    with pytest.raises(ChangeNotApplicable):
        ledger.apply(change.change_id, actor="demo-operator")
    with pytest.raises(ChangeNotApplicable):
        ledger.discard(change.change_id, actor="demo-operator")


def test_apply_unknown_change_id_refuses(config):
    ledger = ChangeLedger(config)
    with pytest.raises(ChangeNotApplicable):
        ledger.apply("chg-9999", actor="demo-operator")


def test_apply_recheck_uses_current_guardrails(config):
    ledger = ChangeLedger(config)
    change = ledger.stage(
        kind=ChangeKind.PRICE_UPDATE,
        summary="涨价 15%",
        items=_price_items(1, before=100.0, after=115.0),
        actor="demo-operator",
    )
    ledger._config = config.model_copy(update={"max_price_delta_pct": 5.0})
    with pytest.raises(GuardrailViolation):
        ledger.apply(change.change_id, actor="demo-operator")


def test_discard_keeps_the_audit_record(config):
    ledger = ChangeLedger(config)
    change = ledger.stage(
        kind=ChangeKind.LISTING_UPDATE,
        summary="更新花盆的描述",
        items=[ChangeItem(target="L-001", field="short_description", before="a", after="b")],
        actor="demo-operator",
    )
    discarded = ledger.discard(change.change_id, actor="demo-operator")
    assert discarded.status is ChangeStatus.DISCARDED
    assert discarded.discarded_at is not None
    assert discarded.discarded_by == "demo-operator"
    assert ledger.pending() == []
    assert ledger.get(change.change_id) == discarded
    with pytest.raises(ChangeNotApplicable):
        ledger.apply(change.change_id, actor="demo-operator")


def test_discard_records_actor_kind(config):
    ledger = ChangeLedger(config)
    first = ledger.stage(
        kind=ChangeKind.PRICE_UPDATE,
        summary="第一条",
        items=_price_items(1),
        actor="demo-operator",
        actor_kind=ActorKind.AGENT,
    )
    second = ledger.stage(
        kind=ChangeKind.PRICE_UPDATE,
        summary="第二条",
        items=_price_items(1),
        actor="demo-operator",
        actor_kind=ActorKind.AGENT,
    )
    agent_discard = ledger.discard(
        first.change_id, actor="demo-operator", actor_kind=ActorKind.AGENT
    )
    assert agent_discard.discarded_by == "demo-operator"
    assert agent_discard.discarded_by_kind is ActorKind.AGENT
    operator_discard = ledger.discard(second.change_id, actor="demo-operator")
    assert operator_discard.discarded_by_kind is ActorKind.OPERATOR
