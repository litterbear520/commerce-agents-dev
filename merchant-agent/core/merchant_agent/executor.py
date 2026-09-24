"""商户 agent 的工具，建在共享执行器框架上，每个工具一个 handler。Messages API 运行时、
SDK 工具集、MCP 服务器和分析委托的读取都通过这个类执行，所以同一个工具在每条路径上返回
相同的字节。暂存调用成功时还会渲染这条变更的预览卡片（``stage_shows_preview``）。
"""
# 项目中对应 merchant-agent/core/merchant_agent/executor.py
# 省略：展示组件（Step 19）；domain_error、get_pending_changes 和暂存写入（Step 20）；
# 分析委托、进度事件（Step 21）；展示扩展

from __future__ import annotations

from typing import Any

from commerce_common.execution import BaseToolExecutor, Handler, parse_argument
from commerce_common.memory import MemoryRuntime
from commerce_common.presentation import PresentationComponent
from commerce_common.skills import SkillRegistry
from commerce_common.streaming import ToolOutcome

from .backend import MerchantBackend
from .config import MerchantAgentConfig
from .fencing import MERCHANT_FENCE
from .memory import MERCHANT_MEMORY_EXTRACTION_PROMPT
from .serialization import (
    alert_record,
    listing_details_payload,
    pricing_context_payload,
    search_result_text,
)
from .types import ListingFilters, MerchantSessionContext, MerchantSessionState


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
    # 项目中是 enrichment.PRESENTATION_COMPONENTS，Step 19 写展示组件时再换
    components: dict[str, PresentationComponent] = {}
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
