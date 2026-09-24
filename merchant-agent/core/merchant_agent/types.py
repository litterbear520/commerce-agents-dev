"""商户领域类型，编排器、MerchantBackend 接口和示例共用：商品条目、指标、分析结果、
库存与订单状况、定价、营销活动、暂存变更、会话状态。采用方在自己的 MerchantBackend
实现里把自己的系统映射到这些模型上。
"""
# 项目中对应 merchant-agent/core/merchant_agent/types.py
# 省略：分析结果（Step 21）、DataLimitation（Step 19）、暂存变更的输入和记录（Step 20）

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from commerce_common.types import remember

# ── 商品条目（商家视角的商品目录） ───────────────────────────────────


class Listing(BaseModel):
    """商家管理的一条商品目录记录，形态和店面的 ``Product`` 一样有三种。plain：普通商品。
    family：带有 ``options``，它的 ``price`` 是最低变体的价格（不论有没有货），``stock``
    是各变体之和。variant：出现在 family 的 ``ListingDetails.variants`` 里，有自己的 id、
    价格、库存和状态，带 ``option_values``，``variant_of`` 是 family 的 id。价格和库存
    按变体读写，所以凡是填 ``listing_id`` 的地方都可以填变体的 id；写入规则在
    ``MerchantBackend`` 上，映射指南是 ``docs/backends.md``。"""

    listing_id: str
    title: str
    status: Literal["active", "paused", "draft", "out_of_stock"] = "active"
    price: float
    currency: str = "USD"
    stock: int = 0
    category: str | None = None
    content_quality: Literal["good", "needs_work", "poor"] | None = None
    attributes: dict[str, str] = Field(default_factory=dict)
    image_url: str | None = None
    short_description: str | None = None
    options: dict[str, list[str]] = Field(default_factory=dict)
    option_values: dict[str, str] = Field(default_factory=dict)
    variant_of: str | None = None

    @property
    def has_options(self) -> bool:
        """family 为 True：价格和库存的写入要指定它的某个变体。"""
        return bool(self.options)


class ListingDetails(Listing):
    """用于编辑和审查的完整商品条目。``review_snippets`` 是买家写的文字。
    普通商品的 ``variants`` 为空。"""

    long_description: str | None = None
    review_snippets: list[str] = Field(default_factory=list)
    sales_last_30d: int | None = None
    return_rate_pct: float | None = None
    missing_attributes: list[str] = Field(default_factory=list)
    variants: list[Listing] = Field(default_factory=list)


class ListingFilters(BaseModel):
    status: Literal["active", "paused", "draft", "out_of_stock"] | None = None
    category: str | None = None
    max_stock: int | None = None
    content_quality: Literal["good", "needs_work", "poor"] | None = None
    sort: Literal["relevance", "sales_desc", "stock_asc", "price_desc", "price_asc"] = "relevance"


# ── 指标 ─────────────────────────────────────────────────────────────


class AlertCounts(BaseModel):
    low_stock: int = 0
    slow_movers: int = 0
    order_issues: int = 0
    pending_changes: int = 0


class BusinessSnapshot(BaseModel):
    """一个统计周期的核心数字，带对比变化和告警数。店铺系统给不出的数字（比如没有分析
    权限时的流量）是 None，绝不用 0 顶替，并由 ``note`` 用一句话说明原因。"""

    period: str
    compare_to: str | None = None
    sales: float
    orders: int
    traffic: int | None = None
    conversion_rate: float | None = None
    average_order_value: float | None = None
    sales_change_pct: float | None = None
    orders_change_pct: float | None = None
    traffic_change_pct: float | None = None
    conversion_change_pct: float | None = None
    currency: str = "USD"
    alerts: AlertCounts = Field(default_factory=AlertCounts)
    note: str | None = Field(default=None, max_length=140)


class MetricPoint(BaseModel):
    date: str
    value: float


class MetricSeries(BaseModel):
    """一个指标随时间的变化，可以只看某个细分（一个类目、一个商品条目）。``note`` 用一句话
    说明这条序列受什么限制（历史有上限、店铺读不到某个数据源）；``points`` 为空且带
    note，表示这个指标拿不到。"""

    metric: str
    unit: str | None = None
    granularity: Literal["day", "week", "month"] = "day"
    period: str | None = None
    segment: str | None = None
    points: list[MetricPoint] = Field(default_factory=list)
    note: str | None = Field(default=None, max_length=140)


# ── 库存与订单状况 ───────────────────────────────────────────────────


class InventoryAlert(BaseModel):
    """针对 family 某个变体的告警，``listing_id`` 填该变体的 id，带上它的
    ``option_values``，``variant_of`` 是 family 的 id。"""

    listing_id: str
    title: str
    kind: Literal["low_stock", "slow_mover"]
    option_values: dict[str, str] = Field(default_factory=dict)
    variant_of: str | None = None
    stock: int
    threshold: int | None = None
    days_of_cover: float | None = None
    sales_last_30d: int | None = None
    # 已暂停和已售罄的商品条目为 False，后端不追踪时为 None。
    # 后台界面里描述店面显示情况的文案以这个字段为准。
    storefront_visible: bool | None = None


class OrderIssue(BaseModel):
    """需要商家处理的订单异常。``buyer_message_excerpt`` 是顾客写的文字。"""

    issue_id: str
    order_id: str
    kind: Literal["delayed", "return_spike", "buyer_message", "damaged"]
    summary: str
    listing_id: str | None = None
    buyer_message_excerpt: str | None = None
    opened_at: datetime | None = None


# ── 定价与营销活动 ───────────────────────────────────────────────────


class PricingContext(BaseModel):
    """服务端算好的、用来判断某个商品条目或变体调价的参考数据。``max_price_delta_pct`` 和
    ``max_promotion_discount_pct`` 重复了部署配置（MerchantAgentConfig）里的调价上限，
    让 agent 在暂存调价之前就能说出来。family 的 ``current_price`` 是最低变体的价格，
    ``variants`` 里每个变体各有一份参考数据。"""

    listing_id: str
    current_price: float
    currency: str = "USD"
    unit_cost: float | None = None
    margin_pct: float | None = None
    min_price: float | None = None
    max_price: float | None = None
    max_price_delta_pct: float | None = None
    max_promotion_discount_pct: float | None = None
    # ``min_price`` 的依据：按商品成本算出来的，或者是不论成本都要守的店铺规定。
    # 后端没说明时为 None。
    min_price_basis: Literal["cost", "policy"] | None = None
    demand_signal: Literal["rising", "steady", "falling"] | None = None
    last_changed: str | None = None
    option_values: dict[str, str] = Field(default_factory=dict)
    variants: list[PricingContext] = Field(default_factory=list)


class Campaign(BaseModel):
    """渠道不报告 ``spend`` 和 ``revenue`` 时它们为 None；为 0 表示渠道报告的就是 0。"""

    campaign_id: str
    name: str
    status: Literal["draft", "active", "paused", "ended"]
    objective: str | None = None
    channel: str | None = None
    budget: float
    spend: float | None = None
    revenue: float | None = None
    currency: str = "USD"
    starts: str | None = None
    ends: str | None = None


# ── 会话 ─────────────────────────────────────────────────────────────


class MerchantSessionContext(BaseModel):
    """调用方为每次请求提供的上下文。``operator`` 会盖在暂存和应用的变更上，所以调用方
    要从自己的身份认证里得出它。如果调用方只允许某个操作员管理特定店铺或执行特定操作，
    就继承这个上下文带上权限范围，并由它的后端在每个方法里执行。"""

    # 项目中继承 ClockContext（带时区和 now），Step 19 再加

    session_id: str
    merchant_id: str
    operator: str


class MerchantSessionState(BaseModel):
    """调用方持有、编排器更新的会话状态。``seen_*`` 字典和 ``latest_snapshot`` 是溯源记录：
    暂存只接受本会话工具返回过的商品条目 id，应用和丢弃只接受工具返回过的变更 id，
    展示型工具的 payload 从这些记录补全，而不是从工具参数里取。
    """

    # 省略：seen_changes、approved_change_ids、host_action_change_ids（Step 20）；
    # seen_analyses、analyses_run（Step 21）

    seen_listings: dict[str, Listing] = Field(default_factory=dict)
    # 本会话 get_listing 返回过完整记录的 id。stage_listing_update 除了 seen_listings
    # 还要求这一条，因为内容编辑是基于完整记录暂存的，而搜索结果只带部分字段。
    read_listings: set[str] = Field(default_factory=set)
    latest_snapshot: BusinessSnapshot | None = None
    seen_series: dict[str, MetricSeries] = Field(default_factory=dict)
    seen_campaigns: dict[str, Campaign] = Field(default_factory=dict)

    def remember_listings(self, listings: list[Listing]) -> None:
        for listing in listings:
            remember(self.seen_listings, listing.listing_id, listing)

    def remember_listing_record(self, listing: Listing) -> None:
        """记录一次完整的 get_listing 读取，这是 stage_listing_update 的前提。
        family 的变体（在 ``ListingDetails`` 上）随它一起进入溯源记录，
        这样价格和库存的写入可以指定它们。"""
        remember(self.seen_listings, listing.listing_id, listing)
        self.read_listings.add(listing.listing_id)
        if isinstance(listing, ListingDetails):
            self.remember_listings(listing.variants)

    def remember_snapshot(self, snapshot: BusinessSnapshot) -> None:
        self.latest_snapshot = snapshot

    def remember_series(self, series: MetricSeries) -> None:
        key = f"{series.metric}:{series.segment}" if series.segment else series.metric
        remember(self.seen_series, key, series)

    def remember_campaigns(self, campaigns: list[Campaign]) -> None:
        for campaign in campaigns:
            remember(self.seen_campaigns, campaign.campaign_id, campaign)
