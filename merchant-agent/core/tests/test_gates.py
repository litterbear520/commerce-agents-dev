"""merchant_agent.gates 里共享会话门控的语义。"""
# 项目中对应 merchant-agent/core/tests/test_gates.py
# 省略：take_discard_actor_kind 的丢弃归属测试（Step 20 第 5 组）

from datetime import UTC, datetime

from merchant_agent import (
    Campaign,
    ChangeItem,
    ChangeKind,
    Listing,
    StagedChange,
)
from merchant_agent.gates import (
    check_apply_change,
    check_campaign_provenance,
    check_discard_change,
    check_listing_provenance,
    check_listing_record_read,
)


def _staged_change(change_id: str = "chg-0001", *, after: float = 105.0) -> StagedChange:
    return StagedChange(
        change_id=change_id,
        kind=ChangeKind.PRICE_UPDATE,
        summary="调价",
        items=[ChangeItem(target="L-201", field="price", before=100.0, after=after)],
        created_at=datetime.now(UTC),
        created_by="demo-operator",
    )


# ── 来源 ──────────────────────────────────────────────────────────────────────


def test_listing_provenance_names_the_unknown_ids(state):
    refusal = check_listing_provenance(state, ["L-201", "L-999"])
    assert refusal is not None
    assert refusal.blocked == "provenance"
    assert "L-201" in refusal.result_text and "L-999" in refusal.result_text

    state.remember_listings([Listing(listing_id="L-201", title="花盆", price=18.0)])
    refusal = check_listing_provenance(state, ["L-201", "L-999"])
    assert refusal is not None and "L-201" not in refusal.result_text
    assert check_listing_provenance(state, ["L-201"]) is None


def test_listing_record_read_gates_content_edits(state):
    # 搜索结果给了 id 的来源，但没有给完整记录的来源。
    state.remember_listings([Listing(listing_id="L-201", title="花盆", price=18.0)])
    refusal = check_listing_record_read(state, "L-201")
    assert refusal is not None
    assert refusal.blocked == "provenance"
    assert "get_listing" in refusal.result_text

    state.remember_listing_record(Listing(listing_id="L-201", title="花盆", price=18.0))
    assert check_listing_record_read(state, "L-201") is None


def test_campaign_provenance_gates_only_existing_campaign_ids(state):
    # 新建营销活动没有 id 可查。
    assert check_campaign_provenance(state, None) is None
    assert check_campaign_provenance(state, "") is None

    refusal = check_campaign_provenance(state, "C-201")
    assert refusal is not None
    assert refusal.blocked == "provenance"
    assert "C-201" in refusal.result_text and "get_campaign_performance" in refusal.result_text

    state.remember_campaigns(
        [
            Campaign(
                campaign_id="C-201",
                name="春季焕新",
                status="active",
                budget=400.0,
                spend=120.0,
                revenue=560.0,
            )
        ]
    )
    assert check_campaign_provenance(state, "C-201") is None


# ── 应用门控 ──────────────────────────────────────────────────────────────────


def test_apply_gate_refuses_unknown_change_ids(state, config):
    refusal = check_apply_change(state, config, "chg-9999")
    assert refusal is not None
    assert refusal.blocked == "provenance"
    assert "不是本次会话暂存或列出过的" in refusal.result_text


def test_apply_gate_rechecks_guardrails_against_current_config(state, config):
    # 100 → 105 是 5% 的变动，在默认 20% 的上限之内。
    state.remember_change(_staged_change(after=105.0))
    assert check_apply_change(state, config, "chg-0001") is None
    tightened = config.model_copy(update={"max_price_delta_pct": 1.0})
    refusal = check_apply_change(state, tightened, "chg-0001")
    assert refusal is not None
    assert refusal.blocked == "guardrail"
    assert "已经不能应用" in refusal.result_text


def test_apply_gate_enforces_host_verified_approval(state, config):
    strict = config.model_copy(update={"require_host_approval": True})
    state.remember_change(_staged_change())
    refusal = check_apply_change(state, strict, "chg-0001")
    assert refusal is not None
    assert refusal.blocked == "approval"
    assert strict.approval_surface in refusal.result_text
    state.approved_change_ids.add("chg-0001")
    assert check_apply_change(state, strict, "chg-0001") is None


# ── 丢弃：来源 ────────────────────────────────────────────────────────────────


def test_discard_gate_refuses_unknown_change_ids(state):
    refusal = check_discard_change(state, "chg-9999")
    assert refusal is not None
    assert refusal.blocked == "provenance"
    assert "没有可丢弃的内容" in refusal.result_text
    state.remember_change(_staged_change())
    assert check_discard_change(state, "chg-0001") is None
