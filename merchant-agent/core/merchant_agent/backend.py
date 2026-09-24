"""MerchantBackend 接口：采用方唯一需要实现的对接接口，把每个方法映射到自己的分析、
商品目录、库存、订单、定价和营销活动系统。这些方法返回的所有内容都会作为围栏数据
到达模型（fencing.py）。``examples/retail/api/mock_merchant.py`` 是一份完整的内存实现。
"""
# 项目中对应 merchant-agent/core/merchant_agent/backend.py
# 省略：暂存写入、get_pending_changes、apply/discard（Step 20）；
# 分析查询（Step 21）；get_merchant_context（Step 19）

from __future__ import annotations

from abc import ABC, abstractmethod

from .types import (
    BusinessSnapshot,
    Campaign,
    InventoryAlert,
    Listing,
    ListingDetails,
    ListingFilters,
    MerchantSessionContext,
    MetricSeries,
    OrderIssue,
    PricingContext,
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
