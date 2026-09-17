"""购物 agent 的共享库。导出外部调用方需要的类型、后端抽象类、配置和序列化器。

提示词、工具契约和门控在各自的子模块里。
"""

from .backend import NotOffered, StorefrontBackend, Unavailable
from .config import ShoppingAgentConfig
from .serialization import (
    cart_payload,
    compact_product,
    fulfillment_payload,
    order_payload,
    orders_payload,
    policies_payload,
    search_result_text,
)
from .types import (
    Cart,
    CartItem,
    CheckoutHandoff,
    FulfillmentOption,
    Order,
    OrderItem,
    OrderStatus,
    Policy,
    Product,
    ProductDetails,
    SearchFilters,
    ShoppingSessionContext,
    ShoppingSessionState,
    UserPreferences,
)

__all__ = [
    "Cart",
    "CartItem",
    "CheckoutHandoff",
    "FulfillmentOption",
    "NotOffered",
    "Order",
    "OrderItem",
    "OrderStatus",
    "Policy",
    "Product",
    "ProductDetails",
    "SearchFilters",
    "ShoppingAgentConfig",
    "ShoppingSessionContext",
    "ShoppingSessionState",
    "StorefrontBackend",
    "Unavailable",
    "UserPreferences",
    "cart_payload",
    "compact_product",
    "fulfillment_payload",
    "order_payload",
    "orders_payload",
    "policies_payload",
    "search_result_text",
]
