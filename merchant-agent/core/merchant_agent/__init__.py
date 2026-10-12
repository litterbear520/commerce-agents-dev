"""商户 agent 的共享库。根模块导出采用方的后端和调用方代码要用的东西：领域类型、
``MerchantBackend``、配置和变更台账。提示词、工具契约、门控和
信息补全在子模块里。
"""
# 项目中对应 merchant-agent/core/merchant_agent/__init__.py
# 省略：分析查询检查 check_analysis_sql 和三个分析结果类型（Step 21）

from .backend import MerchantBackend
from .changes import ChangeLedger, ChangeNotApplicable, GuardrailViolation
from .config import MerchantAgentConfig
from .types import (
    ActorKind,
    AlertCounts,
    BusinessSnapshot,
    Campaign,
    CampaignDraft,
    ChangeItem,
    ChangeKind,
    ChangeStatus,
    DataLimitation,
    InventoryActionItem,
    InventoryAlert,
    Listing,
    ListingDetails,
    ListingFilters,
    MerchantSessionContext,
    MerchantSessionState,
    MetricPoint,
    MetricSeries,
    OrderIssue,
    PriceUpdateItem,
    PricingContext,
    PromotionDraft,
    StagedChange,
)

__all__ = [
    "ActorKind",
    "AlertCounts",
    "BusinessSnapshot",
    "Campaign",
    "CampaignDraft",
    "ChangeItem",
    "ChangeKind",
    "ChangeLedger",
    "ChangeNotApplicable",
    "ChangeStatus",
    "DataLimitation",
    "GuardrailViolation",
    "InventoryActionItem",
    "InventoryAlert",
    "Listing",
    "ListingDetails",
    "ListingFilters",
    "MerchantAgentConfig",
    "MerchantBackend",
    "MerchantSessionContext",
    "MerchantSessionState",
    "MetricPoint",
    "MetricSeries",
    "OrderIssue",
    "PriceUpdateItem",
    "PricingContext",
    "PromotionDraft",
    "StagedChange",
]
