"""商户领域类型，编排器、MerchantBackend 接口和示例共用：商品条目、指标、分析结果、
库存与订单状况、定价、营销活动、暂存变更、会话状态。采用方在自己的 MerchantBackend
实现里把自己的系统映射到这些模型上。
"""
# 项目中对应 merchant-agent/core/merchant_agent/types.py
# 省略：分析结果（Step 21）

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

from commerce_common.types import ClockContext, remember

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


class DataLimitation(BaseModel):
    """店铺系统给不了当前部署的一类数据，放进 ``MerchantBackend.get_merchant_context``
    返回的 ``limitations`` 列表。例如：订单历史只能往前查一段时间，店铺套餐不含某个流量
    来源，别的工具建的营销活动这里读不到。"""

    source: str = Field(max_length=40)
    note: str = Field(max_length=140)


# ── 暂存变更的输入（agent 传给 stage_* 工具的内容） ─────────────────────


class PriceUpdateItem(BaseModel):
    """``listing_id`` 是普通商品或某个变体的 id；family 要改价时，每个变体各占一条。"""

    listing_id: str
    new_price: float = Field(gt=0)


class InventoryActionItem(BaseModel):
    """补货要指定普通商品或某个变体；暂停和重新上架也可以指定 family，这时它的所有
    变体一起下架或上架。"""

    listing_id: str
    action: Literal["restock", "pause", "activate"]
    quantity: int | None = Field(default=None, ge=0)


class PromotionDraft(BaseModel):
    """一段有起止日期的调价。``discount_pct`` 为正表示降价，为负表示在这段时间里涨价。
    ``nights`` 把调价限定在一周里的某几晚；没有按晚区分的后端会忽略它。"""

    name: str = Field(max_length=80)
    listing_ids: list[str] = Field(min_length=1)
    discount_pct: float = Field(ge=-90, le=90)
    starts: str
    ends: str
    nights: list[Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]] | None = None


class CampaignDraft(BaseModel):
    """要新建的营销活动，或对已有活动（``campaign_id``）的预算、文案修改。"""

    campaign_id: str | None = None
    name: str = Field(max_length=80)
    objective: str | None = Field(default=None, max_length=200)
    audience: str | None = Field(default=None, max_length=300)
    budget: float | None = Field(default=None, ge=0)
    copy_text: str | None = Field(default=None, max_length=600)
    starts: str | None = None
    ends: str | None = None


# ── 暂存变更（提议 → 预览 → 审批 → 应用 这道关） ──────────────────────


class ChangeKind(StrEnum):
    LISTING_UPDATE = "listing_update"
    PRICE_UPDATE = "price_update"
    INVENTORY_ACTION = "inventory_action"
    PROMOTION = "promotion"
    CAMPAIGN = "campaign"


class ChangeStatus(StrEnum):
    STAGED = "staged"
    APPLIED = "applied"
    DISCARDED = "discarded"


class ActorKind(StrEnum):
    """一个操作由谁发起：经营者自己，或者助手代经营者操作。两种情况旁边记下的主体都是
    经营者。"""

    OPERATOR = "operator"
    AGENT = "agent"


class ChangeItem(BaseModel):
    """暂存变更里的一条字段级差异。``target`` 标明受影响的记录（商品条目 id、营销活动
    id、促销名称）。"""

    target: str
    field: str
    before: Any = None
    after: Any = None


class StagedChange(BaseModel):
    """一笔提议中的写入，等待对它的 ``change_id`` 审批。几个操作者字段就是审计记录：
    ``created_by`` 和 ``discarded_by`` 记的是经营者这个主体，``*_kind`` 字段记下是不是
    助手代经营者做的；``applied_by`` 没有助手这一种，因为审批永远是经营者的。

    金额字段由后端计算。``currency`` 适用于 ``items`` 和毛利字段里的每一个金额；
    ``margin_before_pct`` / ``margin_after_pct`` 只在单个商品条目调价时填写，多条目的
    变更改为在 ``guardrail_notes`` 里逐条写毛利。某一条的成本未知时毛利为 None，
    绝不按假设的成本去算。"""

    change_id: str
    kind: ChangeKind
    status: ChangeStatus = ChangeStatus.STAGED
    summary: str = Field(max_length=200)
    items: list[ChangeItem] = Field(default_factory=list)
    created_at: datetime
    created_by: str
    created_by_kind: ActorKind = ActorKind.OPERATOR
    applied_at: datetime | None = None
    applied_by: str | None = None
    discarded_at: datetime | None = None
    discarded_by: str | None = None
    discarded_by_kind: ActorKind | None = None
    guardrail_notes: list[str] = Field(default_factory=list)
    currency: str | None = None
    margin_impact: float | None = None
    margin_before_pct: float | None = None
    margin_after_pct: float | None = None


# ── 会话 ─────────────────────────────────────────────────────────────


class MerchantSessionContext(ClockContext):
    """调用方为每次请求提供的上下文。``operator`` 会盖在暂存和应用的变更上，所以调用方
    要从自己的身份认证里得出它。如果调用方只允许某个操作员管理特定店铺或执行特定操作，
    就继承这个上下文带上权限范围，并由它的后端在每个方法里执行。"""

    session_id: str
    merchant_id: str
    operator: str


class MerchantSessionState(BaseModel):
    """调用方持有、编排器更新的会话状态。``seen_*`` 字典和 ``latest_snapshot`` 是溯源记录：
    暂存只接受本会话工具返回过的商品条目 id，应用和丢弃只接受工具返回过的变更 id，
    展示型工具的 payload 从这些记录补全，而不是从工具参数里取。
    """

    # 省略：seen_analyses、analyses_run（Step 21）

    seen_listings: dict[str, Listing] = Field(default_factory=dict)
    # 本会话 get_listing 返回过完整记录的 id。stage_listing_update 除了 seen_listings
    # 还要求这一条，因为内容编辑是基于完整记录暂存的，而搜索结果只带部分字段。
    read_listings: set[str] = Field(default_factory=set)
    seen_changes: dict[str, StagedChange] = Field(default_factory=dict)
    latest_snapshot: BusinessSnapshot | None = None
    seen_series: dict[str, MetricSeries] = Field(default_factory=dict)
    seen_campaigns: dict[str, Campaign] = Field(default_factory=dict)
    # 调用方已记下审批的变更 id（后台按钮、命令行确认）。只在 config.require_host_approval
    # 打开时才查它；这时 apply_change 拒绝任何不在这个集合里的 id。
    approved_change_ids: set[str] = Field(default_factory=set)
    # 由经营者在调用方界面上触发丢弃的变更 id。调用方先加上这个 id，再把操作交给执行器，
    # 执行器据此把 ``discarded_by_kind`` 记成经营者。只有调用方会写它，所以模型没法把
    # 自己的丢弃算到经营者头上。
    host_action_change_ids: set[str] = Field(default_factory=set)

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

    def remember_change(self, change: StagedChange) -> None:
        remember(self.seen_changes, change.change_id, change)

    def remember_snapshot(self, snapshot: BusinessSnapshot) -> None:
        self.latest_snapshot = snapshot

    def remember_series(self, series: MetricSeries) -> None:
        key = f"{series.metric}:{series.segment}" if series.segment else series.metric
        remember(self.seen_series, key, series)

    def remember_campaigns(self, campaigns: list[Campaign]) -> None:
        for campaign in campaigns:
            remember(self.seen_campaigns, campaign.campaign_id, campaign)
