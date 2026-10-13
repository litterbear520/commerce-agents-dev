"""商户 agent 的工具，建在共享执行器框架上，每个工具一个 handler。Messages API 运行时、
SDK 工具集、MCP 服务器和分析委托的读取都通过这个类执行，所以同一个工具在每条路径上返回
相同的字节。暂存调用成功时还会渲染这条变更的预览卡片（``stage_shows_preview``）。
"""
# 项目中对应 merchant-agent/core/merchant_agent/executor.py
# 省略：分析委托、进度事件（Step 21）；展示扩展

from __future__ import annotations

from typing import Any

from commerce_common.execution import BaseToolExecutor, Handler, parse_argument
from commerce_common.fencing import truncate_display
from commerce_common.memory import MemoryRuntime
from commerce_common.skills import SkillRegistry
from commerce_common.streaming import AgentEvent, ToolOutcome

from .backend import MerchantBackend
from .changes import ChangeNotApplicable, GuardrailViolation
from .config import MerchantAgentConfig
from .enrichment import PRESENTATION_COMPONENTS
from .fencing import MERCHANT_FENCE
from .gates import (
    GUARDRAIL_GATE,
    STAGED_AND_SHOWN_NOTE,
    STAGED_NOTE,
    applied_confirmation,
    apply_guardrail_message,
    check_apply_change,
    check_campaign_provenance,
    check_discard_change,
    check_listing_options,
    check_listing_provenance,
    check_listing_record_read,
    check_promotion_depth,
    coerce_array_arg,
    coerce_object_arg,
    guardrail_block_message,
    take_discard_actor_kind,
)
from .memory import MERCHANT_MEMORY_EXTRACTION_PROMPT
from .serialization import (
    alert_record,
    listing_details_payload,
    pricing_context_payload,
    search_result_text,
)
from .tools.presentation import PREVIEW_TOOL
from .types import (
    CampaignDraft,
    InventoryActionItem,
    ListingFilters,
    MerchantSessionContext,
    MerchantSessionState,
    PriceUpdateItem,
    PromotionDraft,
    StagedChange,
)

# 暂存说明是审批卡上的展示文字；上限就是注册表里 note 的 maxLength，截断后的说明也
# 不会超过 StagedChange.summary 的上限。
NOTE_MAX_CHARS = 200
PROMOTION_TEXT_MAX_CHARS = 300
CAMPAIGN_TEXT_MAX_CHARS = 600


def build_memory(
    config: MerchantAgentConfig, store: Any, write_filter: Any = None
) -> MemoryRuntime:
    """商户 agent 的 :class:`MemoryRuntime`：按这份配置包装的 store，按商户 id 归属，
    用商户场景的提取提示词做提取。"""
    return MemoryRuntime.build(
        config,
        store,
        fence=MERCHANT_FENCE,
        extraction_prompt=MERCHANT_MEMORY_EXTRACTION_PROMPT,
        write_filter=write_filter,
    )


def _record(model: Any) -> dict[str, Any]:
    return model.model_dump(mode="json", exclude_none=True)


class MerchantToolExecutor(BaseToolExecutor):
    fence = MERCHANT_FENCE
    components = PRESENTATION_COMPONENTS
    displayed_text = "已展示给经营者。"
    unavailable_text = "{name} 暂时不可用。用已有的信息继续，或者告诉经营者。"
    absent_text = "{name} 不是这个后台提供的功能；直接说明，不要推荐它。"

    def __init__(
        self,
        *,
        backend: MerchantBackend,
        config: MerchantAgentConfig,
        skills: SkillRegistry,
        session: MerchantSessionContext,
        state: MerchantSessionState,
        memory: MemoryRuntime | None = None,
    ) -> None:
        super().__init__(
            backend=backend,
            config=config,
            skills=skills,
            session=session,
            state=state,
            memory=memory or build_memory(config, None),
        )

    @property
    def memory_subject(self) -> str:
        return self._session.merchant_id

    def domain_error(self, error: Exception) -> ToolOutcome | None:
        if isinstance(error, GuardrailViolation):
            return ToolOutcome.held(GUARDRAIL_GATE, guardrail_block_message(error.violations))
        if isinstance(error, ChangeNotApplicable):
            # 后端文字在围栏外到达：清洗并限长。
            return ToolOutcome.error(self._sanitize(str(error), 300))
        return None

    def handlers(self) -> dict[str, Handler]:
        return {
            "get_business_snapshot": self._get_business_snapshot,
            "query_metrics": self._query_metrics,
            "get_campaign_performance": self._get_campaign_performance,
            "search_listings": self._search_listings,
            "get_listing": self._get_listing,
            "get_inventory_alerts": self._get_inventory_alerts,
            "get_order_issues": self._get_order_issues,
            "get_pricing_context": self._get_pricing_context,
            "get_pending_changes": self._get_pending_changes,
            "stage_listing_update": self._stage_listing_update,
            "stage_price_update": self._stage_price_update,
            "stage_inventory_action": self._stage_inventory_action,
            "stage_promotion": self._stage_promotion,
            "stage_campaign": self._stage_campaign,
            "apply_change": self._apply_change,
            "discard_change": self._discard_change,
        }

    # ── 读取 ────────────────────────────────────────────────────────

    async def _get_business_snapshot(self, tool_input: dict[str, Any]) -> ToolOutcome:
        period = self._sanitize(tool_input.get("period"), 60) or None
        snapshot = await self._backend.get_business_snapshot(self._session, period)
        self._state.remember_snapshot(snapshot)
        return self._fenced(_record(snapshot))

    async def _query_metrics(self, tool_input: dict[str, Any]) -> ToolOutcome:
        series = await self._backend.query_metrics(
            self._session,
            self._sanitize(tool_input.get("metric"), 60),
            self._sanitize(tool_input.get("period"), 60) or None,
            str(tool_input.get("granularity") or "day"),
            self._sanitize(tool_input.get("segment"), 80) or None,
        )
        self._state.remember_series(series)
        return self._fenced(_record(series))

    async def _get_campaign_performance(self, tool_input: dict[str, Any]) -> ToolOutcome:
        campaign_id = str(tool_input.get("campaign_id") or "") or None
        campaigns = await self._backend.get_campaign_performance(self._session, campaign_id)
        self._state.remember_campaigns(campaigns)
        payload = [_record(campaign) for campaign in campaigns]
        return self._fenced(payload or {"note": "没有找到营销活动。"})

    async def _search_listings(self, tool_input: dict[str, Any]) -> ToolOutcome:
        query = self._sanitize(tool_input.get("query"), 300)
        filters = (
            parse_argument(ListingFilters, tool_input["filters"])
            if tool_input.get("filters")
            else None
        )
        limit = self._search_limit(tool_input.get("limit"))
        listings = await self._backend.search_listings(self._session, query, filters, limit)
        self._state.remember_listings(listings)
        return ToolOutcome(search_result_text(query, listings, self._config.max_fenced_chars))

    async def _get_listing(self, tool_input: dict[str, Any]) -> ToolOutcome:
        listing_id = str(tool_input.get("listing_id", ""))
        details = await self._backend.get_listing(self._session, listing_id)
        if details is None:
            return ToolOutcome.error(f"没有 id 为 {listing_id} 的商品条目。")
        self._state.remember_listing_record(details)
        return self._fenced(listing_details_payload(details))

    async def _get_inventory_alerts(self, _: dict[str, Any]) -> ToolOutcome:
        alerts = await self._backend.get_inventory_alerts(self._session)
        payload = [alert_record(alert) for alert in alerts]
        return self._fenced(payload or {"note": "目前没有库存告警。"})

    async def _get_order_issues(self, _: dict[str, Any]) -> ToolOutcome:
        issues = await self._backend.get_order_issues(self._session)
        payload = [_record(issue) for issue in issues]
        return self._fenced(payload or {"note": "没有未处理的订单异常。"})

    async def _get_pricing_context(self, tool_input: dict[str, Any]) -> ToolOutcome:
        listing_id = str(tool_input.get("listing_id", ""))
        context = await self._backend.get_pricing_context(self._session, listing_id)
        if context is None:
            return ToolOutcome.error(f"商品条目 {listing_id} 没有定价参考数据。")
        return self._fenced(pricing_context_payload(context))

    async def _get_pending_changes(self, _: dict[str, Any]) -> ToolOutcome:
        pending = await self._backend.get_pending_changes(self._session)
        for change in pending:
            self._state.remember_change(change)
        payload = [_record(change) for change in pending]
        return self._fenced(payload or {"note": "没有等待审批的变更。"})

    # ── 暂存写入 ────────────────────────────────────────────────────

    def _note(self, tool_input: dict[str, Any]) -> str | None:
        return (
            truncate_display(self._sanitize(tool_input.get("note"), None), NOTE_MAX_CHARS) or None
        )

    def _sanitized_draft(self, tool_input: dict[str, Any], max_chars: int) -> dict[str, Any]:
        return {
            key: self._sanitize(value, max_chars) if isinstance(value, str) else value
            for key, value in tool_input.items()
        }

    async def _staged(self, change: StagedChange) -> ToolOutcome:
        """暂存记录给模型，``change_update`` 给调用方；``stage_shows_preview`` 打开时还有
        预览卡，用的是 present_change_preview 同一套运行流程和补全逻辑，所以门户登记这条
        变更待审批的方式也一样。"""
        self._state.remember_change(change)
        events = [AgentEvent.change_update(_record(change))]
        note = STAGED_NOTE
        if self._config.stage_shows_preview:
            preview = await self._present(
                self.components[PREVIEW_TOOL], {"change_id": change.change_id}
            )
            if not preview.refused:
                events.extend(preview.events)
                note = STAGED_AND_SHOWN_NOTE
        return self._fenced({"staged": _record(change), "note": note}, events)

    async def _stage_listing_update(self, tool_input: dict[str, Any]) -> ToolOutcome:
        listing_id = str(tool_input.get("listing_id", ""))
        if held := check_listing_provenance(self._state, [listing_id]) or check_listing_record_read(
            self._state, listing_id
        ):
            return held
        fields = coerce_object_arg(tool_input.get("fields")) or {}
        if not fields:
            return ToolOutcome.error("没有要修改的字段。")
        # 内容一经审批就上线：超长的值直接拒绝并说明上限，而不是截断后写进线上的商品条目。
        cap = self._config.max_listing_field_chars
        for name, value in fields.items():
            if isinstance(value, str) and len(value) > cap:
                return ToolOutcome.error(
                    f"「{name}」有 {len(value)} 个字符，每个商品条目字段的上限是 {cap}。"
                    "缩短后再暂存一次。"
                )
        cleaned = {
            str(name): self._sanitize(value, cap) if isinstance(value, str) else value
            for name, value in fields.items()
        }
        change = await self._backend.stage_listing_update(
            self._session, listing_id, cleaned, self._note(tool_input)
        )
        return await self._staged(change)

    async def _stage_price_update(self, tool_input: dict[str, Any]) -> ToolOutcome:
        items = [
            parse_argument(PriceUpdateItem, item)
            for item in coerce_array_arg(tool_input.get("items")) or []
        ]
        if not items:
            return ToolOutcome.error("没有要暂存的调价。")
        ids = [item.listing_id for item in items]
        if held := check_listing_provenance(self._state, ids) or check_listing_options(
            self._state, ids, "改价"
        ):
            return held
        change = await self._backend.stage_price_update(
            self._session, items, self._note(tool_input)
        )
        return await self._staged(change)

    async def _stage_inventory_action(self, tool_input: dict[str, Any]) -> ToolOutcome:
        items = [
            parse_argument(InventoryActionItem, item)
            for item in coerce_array_arg(tool_input.get("items")) or []
        ]
        if not items:
            return ToolOutcome.error("没有要暂存的库存操作。")
        restocked = [item.listing_id for item in items if item.action == "restock"]
        if held := check_listing_provenance(
            self._state, [item.listing_id for item in items]
        ) or check_listing_options(self._state, restocked, "补货"):
            return held
        change = await self._backend.stage_inventory_action(
            self._session, items, self._note(tool_input)
        )
        return await self._staged(change)

    async def _stage_promotion(self, tool_input: dict[str, Any]) -> ToolOutcome:
        promotion = parse_argument(
            PromotionDraft, self._sanitized_draft(tool_input, PROMOTION_TEXT_MAX_CHARS)
        )
        if promotion.discount_pct == 0:
            return ToolOutcome.error("促销的调价幅度不能为零。")
        if held := check_promotion_depth(promotion, self._config) or check_listing_provenance(
            self._state, promotion.listing_ids
        ):
            return held
        return await self._staged(await self._backend.stage_promotion(self._session, promotion))

    async def _stage_campaign(self, tool_input: dict[str, Any]) -> ToolOutcome:
        campaign = parse_argument(
            CampaignDraft, self._sanitized_draft(tool_input, CAMPAIGN_TEXT_MAX_CHARS)
        )
        if held := check_campaign_provenance(self._state, campaign.campaign_id):
            return held
        return await self._staged(await self._backend.stage_campaign(self._session, campaign))

    async def _apply_change(self, tool_input: dict[str, Any]) -> ToolOutcome:
        change_id = str(tool_input.get("change_id", ""))
        if held := check_apply_change(self._state, self._config, change_id):
            return held
        try:
            applied = await self._backend.apply_change(self._session, change_id)
        except GuardrailViolation as violation:  # 后端自己的规则更严
            return ToolOutcome.held(GUARDRAIL_GATE, apply_guardrail_message(violation.violations))
        self._state.remember_change(applied)
        return ToolOutcome(
            applied_confirmation(change_id, applied.kind.value, self._session.operator),
            [AgentEvent.change_update(_record(applied))],
        )

    async def _discard_change(self, tool_input: dict[str, Any]) -> ToolOutcome:
        change_id = str(tool_input.get("change_id", ""))
        if held := check_discard_change(self._state, change_id):
            return held
        discarded = await self._backend.discard_change(
            self._session, change_id, actor_kind=take_discard_actor_kind(self._state, change_id)
        )
        self._state.remember_change(discarded)
        return ToolOutcome(f"已丢弃 {change_id}。", [AgentEvent.change_update(_record(discarded))])
