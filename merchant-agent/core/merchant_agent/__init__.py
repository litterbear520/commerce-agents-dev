"""商户 agent 的共享库。根模块导出采用方的后端和调用方代码要用的东西：领域类型、
``MerchantBackend``、配置、变更台账，以及分析查询检查。提示词、工具契约、门控和
信息补全在子模块里。
"""
# 项目中对应 merchant-agent/core/merchant_agent/__init__.py
# 省略：变更台账（Step 20）、分析检查（Step 21）

from .backend import MerchantBackend
from .config import MerchantAgentConfig
from .types import (
    AlertCounts,
    BusinessSnapshot,
    Campaign,
    DataLimitation,
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
    "DataLimitation",
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
    "PricingContext",
]
