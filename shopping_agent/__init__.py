"""购物 agent 的共享库。导出外部调用方需要的类型、后端抽象类、配置和序列化器。

执行器、门控、提示词从各自的子模块导入。
"""

from .backend import NotOffered, StorefrontBackend, Unavailable
from .config import ShoppingAgentConfig
from .serialization import cart_payload, compact_product, search_result_text
from .types import (
    Cart,
    CartItem,
    Product,
    ProductDetails,
    SearchFilters,
    ShoppingSessionContext,
    ShoppingSessionState,
)

__all__ = [
    "Cart",
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
