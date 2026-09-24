"""商户 agent 的共享库。根模块导出采用方的后端和调用方代码要用的东西：领域类型、
``MerchantBackend``、配置、变更台账，以及分析查询检查。提示词、工具契约、门控和
信息补全在子模块里。
"""
# 项目中对应 merchant-agent/core/merchant_agent/__init__.py
# 当前只有类型和后端接口；配置、变更台账、分析检查随后续步骤加入

from .backend import MerchantBackend
from .types import (
    AlertCounts,
    BusinessSnapshot,
    Campaign,
    InventoryAlert,
    Listing,
    ListingDetails,
    ListingFilters,
    MerchantSessionContext,
    MerchantSessionState,
    MetricPoint,
    MetricSeries,
    OrderIssue,
    PricingContext,
)

__all__ = [
    "AlertCounts",
    "BusinessSnapshot",
    "Campaign",
    "InventoryAlert",
    "Listing",
    "ListingDetails",
    "ListingFilters",
    "MerchantBackend",
    "MerchantSessionContext",
    "MerchantSessionState",
    "MetricPoint",
    "MetricSeries",
    "OrderIssue",
    "PricingContext",
]
