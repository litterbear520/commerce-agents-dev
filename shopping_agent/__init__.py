"""购物 agent 的共享库。导出外部调用方需要的类型、后端抽象类、配置和序列化器。

提示词、工具契约和门控在各自的子模块里。
"""

from .backend import NotOffered, StorefrontBackend, Unavailable
from .config import ShoppingAgentConfig
from .serialization import cart_payload, compact_product, search_result_text
from .types import (
    Cart,
    CartItem,
    CheckoutHandoff,
    Product,
    ProductDetails,
    SearchFilters,
    ShoppingSessionContext,
    ShoppingSessionState,
)

__all__ = [
    "Cart",
    "CheckoutHandoff",
    "CartItem",
    "NotOffered",
    "Product",
    "ProductDetails",
    "SearchFilters",
    "ShoppingAgentConfig",
    "ShoppingSessionContext",
    "ShoppingSessionState",
    "StorefrontBackend",
    "Unavailable",
    "cart_payload",
    "compact_product",
    "search_result_text",
]
