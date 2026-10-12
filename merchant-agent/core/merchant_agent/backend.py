"""MerchantBackend 接口：采用方唯一需要实现的对接接口，把每个方法映射到自己的分析、
商品目录、库存、订单、定价和营销活动系统。这些方法返回的所有内容都会作为围栏数据
到达模型（fencing.py）。``examples/retail/api/mock_merchant.py`` 是一份完整的内存实现。
"""
# 项目中对应 merchant-agent/core/merchant_agent/backend.py
# 省略：分析查询（Step 21）

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .types import (
    ActorKind,
    BusinessSnapshot,
    Campaign,
    CampaignDraft,
    InventoryActionItem,
    InventoryAlert,
    Listing,
    ListingDetails,
    ListingFilters,
    MerchantSessionContext,
    MetricSeries,
    OrderIssue,
    PriceUpdateItem,
    PricingContext,
    PromotionDraft,
    StagedChange,
)


class MerchantBackend(ABC):
    """读方法可以随便调；``stage_*`` 方法只记录一份提议，不碰线上状态；只有
    ``apply_change`` 会改动东西：它执行平台写入，而且只对当前处于暂存状态的变更执行。
    每个方法都在服务端、用调用方为这个会话持有的凭证去调商家的系统；模型只看到结果，
    从不看到 token。后端执行业务规则（changes.py 里的护栏加上它自己的规则），并在每条
    变更上盖上会话的操作员。部署里没有的系统，对应方法抛出
    :class:`~merchant_agent.changes.ChangeNotApplicable` 并说明哪部分没有接管，执行器会
    转告；其他任何异常都按临时故障报告。

    带选项的商品条目（``Listing.options``）。搜索返回 family，从不返回它的变体。
    对 family 调 ``get_listing`` 和 ``get_pricing_context`` 会每个变体返回一行，对变体的
    id 调则返回那个变体。调价或补货要指定变体，指定 family 会被拒绝；执行器在它们到达
    后端之前就拦下。暂停、重新上架或促销可以指定 family，此时覆盖它的每个变体，每个
    变体都计入 ``max_items_per_change``。内容编辑两者都可以指定；如果后端的变体和 family
    共用内容字段，就拒绝在变体上改这些字段。
    """

    # ── 经营表现 ────────────────────────────────────────────────────

    @abstractmethod
    async def get_business_snapshot(
        self, session: MerchantSessionContext, period: str | None = None
    ) -> BusinessSnapshot:
        """``period`` 的核心数字，默认是当前统计周期。店铺给不出的数字为 None 并带
        ``note``；这里的合计和 ``query_metrics`` 为同一周期返回的序列应该对得上，因为
        两者都会被引用。"""

    @abstractmethod
    async def query_metrics(
        self,
        session: MerchantSessionContext,
        metric: str,
        period: str | None = None,
        granularity: str = "day",
        segment: str | None = None,
    ) -> MetricSeries:
        """一个指标随时间的变化，可以缩小到某个细分，比如一个类目。店铺给不出的指标或
        某段历史，返回时不带数据点，并用 ``note`` 说明原因。"""

    @abstractmethod
    async def get_campaign_performance(
        self, session: MerchantSessionContext, campaign_id: str | None = None
    ) -> list[Campaign]:
        """全部营销活动，或者 ``campaign_id`` 指定的那一个。不报告花费或收入的渠道，
        这两项留空为 None；这个后端完全看不到的营销活动，作为
        :meth:`get_merchant_context` 里的一条 ``limitations`` 说明。"""

    # ── 商品目录 ────────────────────────────────────────────────────

    @abstractmethod
    async def search_listings(
        self,
        session: MerchantSessionContext,
        query: str,
        filters: ListingFilters | None = None,
        limit: int = 8,
    ) -> list[Listing]:
        """按文本和结构化筛选条件搜索店铺的商品条目；一个 family 算一条结果。"""

    @abstractmethod
    async def get_listing(
        self, session: MerchantSessionContext, listing_id: str
    ) -> ListingDetails | None:
        """一个商品条目的完整记录；id 不存在时返回 None。"""

    # ── 库存与订单状况 ──────────────────────────────────────────────

    @abstractmethod
    async def get_inventory_alerts(self, session: MerchantSessionContext) -> list[InventoryAlert]:
        """当前的低库存和滞销告警。没有告警对象的平台，从库存和销量推算，只返回它能算出
        的类型；空列表表示没有需要提醒的。"""

    @abstractmethod
    async def get_order_issues(self, session: MerchantSessionContext) -> list[OrderIssue]:
        """未处理的订单异常。没有异常对象的平台，从订单推算，只返回它能算出的类型；
        空列表表示没有未处理的。"""

    # ── 定价 ────────────────────────────────────────────────────────

    @abstractmethod
    async def get_pricing_context(
        self, session: MerchantSessionContext, listing_id: str
    ) -> PricingContext | None:
        """一个商品条目或变体的定价参考数据；id 不存在时返回 None。"""

    # ── 暂存写入（提议 → 预览 → 审批 → 应用）──────────────────────────

    @abstractmethod
    async def stage_listing_update(
        self,
        session: MerchantSessionContext,
        listing_id: str,
        fields: dict[str, Any],
        note: str | None = None,
    ) -> StagedChange:
        """暂存对一个商品条目的内容和属性编辑。后端把这些字段对应到自己的字段上；几个
        字段在它那里存成同一个字段时，可以拒绝这种组合（抛出
        :class:`~merchant_agent.changes.ChangeNotApplicable` 并说明是哪个字段）。"""

    @abstractmethod
    async def stage_price_update(
        self,
        session: MerchantSessionContext,
        items: list[PriceUpdateItem],
        note: str | None = None,
    ) -> StagedChange:
        """暂存一个或多个商品条目或变体的价格修改。"""

    @abstractmethod
    async def stage_inventory_action(
        self,
        session: MerchantSessionContext,
        items: list[InventoryActionItem],
        note: str | None = None,
    ) -> StagedChange:
        """暂存一个或多个商品条目的补货或上下架变更。"""

    @abstractmethod
    async def stage_promotion(
        self, session: MerchantSessionContext, promotion: PromotionDraft
    ) -> StagedChange:
        """暂存一个促销。"""

    @abstractmethod
    async def stage_campaign(
        self, session: MerchantSessionContext, campaign: CampaignDraft
    ) -> StagedChange:
        """暂存一个新营销活动，或对 ``campaign.campaign_id`` 指定的活动的修改。"""

    @abstractmethod
    async def get_pending_changes(self, session: MerchantSessionContext) -> list[StagedChange]:
        """已暂存、还没应用也没丢弃的变更。"""

    @abstractmethod
    async def apply_change(self, session: MerchantSessionContext, change_id: str) -> StagedChange:
        """应用一条已审批的变更：先写进这个后端对接的线上系统，再标记为已应用，并记下是谁、
        在什么时候应用的。这个方法就是平台写入，只更新自己变更记录的后端，店铺那边什么都
        没变。不是当前暂存状态的变更要拒绝；写入失败就抛异常，让变更保持暂存。"""

    @abstractmethod
    async def discard_change(
        self,
        session: MerchantSessionContext,
        change_id: str,
        actor_kind: ActorKind = ActorKind.OPERATOR,
    ) -> StagedChange:
        """丢弃一条暂存的变更。``actor_kind`` 记录丢弃是操作员还是助手发起的；无论哪种，
        ``discarded_by`` 都写操作员。"""

    # ── 商户上下文 ──────────────────────────────────────────────────

    async def get_merchant_context(self, session: MerchantSessionContext) -> dict[str, Any] | None:
        """可选的店铺上下文（店铺资料、报表周期、告警数），放进动态提示词块。每次请求都会
        带上，所以要精简；默认返回 None。``limitations`` 键放
        :class:`~merchant_agent.types.DataLimitation` 条目，列出店铺系统给不了的数据；
        回答涉及其中一项时，助手说明它拿不到，而不是报一个零。"""
        return None
