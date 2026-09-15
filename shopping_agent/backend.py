"""StorefrontBackend 接口：采用方唯一需要实现的对接接口，
将每个方法映射到自己的商品目录、购物车等服务。
这些方法返回的所有内容都会经过围栏处理后才到达模型（fencing.py）。
"""
# 项目中对应 shopping-agent/core/shopping_agent/backend.py
# 当前只包含 6 个抽象方法（search + details + cart CRUD），Step 13 扩展到 11 个

from __future__ import annotations

from abc import ABC, abstractmethod

from .types import (
    Cart,
    Product,
    ProductDetails,
    SearchFilters,
    ShoppingSessionContext,
)


class NotOffered(Exception):
    """后端方法抛出此异常表示当前商品或场景不提供该服务
    （例如某个卖家不支持配送），而不是系统故障。
    执行器会告诉模型"该店不提供此服务"。"""


class Unavailable(Exception):
    """``add_to_cart`` 抛出此异常表示商品存在但当前无法购买（缺货等）。
    消息只包含 id：哪个商品不可用，以及（如果是变体的话）哪些同级变体有货。
    执行器会转达给模型，购物车不做任何写入。"""


class StorefrontBackend(ABC):
    """每个方法代表 ``session`` 中的顾客操作，在服务端用它为会话持有的凭证调用对应系统的
    API；模型只看到方法的返回结果，看不到凭证。购物车方法是唯一的写操作；每次写入都
    经过执行器的溯源门控和数量上限（gates.py），并返回完整购物车，后端仍需在自己这边
    原子地执行业务规则（资格、库存、限额），因为执行器的锁只覆盖单进程内的会话。
    没有任何方法会下单或转账：``checkout`` 只是把购物车渲染出来交给服务端完成。
    """

    # ── 商品目录 ────────────────────────────────────────────────────

    @abstractmethod
    async def search_products(
        self,
        session: ShoppingSessionContext,
        query: str,
        filters: SearchFilters | None = None,
        limit: int = 8,
    ) -> list[Product]:
        """最接近的文本匹配结果，按相关度排序，最多 ``limit`` 条；
        没有匹配时返回空列表。family 商品算一条结果（它的变体不单独出现），
        id 通过 :meth:`get_product_details` 解析。"""

    @abstractmethod
    async def get_product_details(
        self, session: ShoppingSessionContext, product_id: str
    ) -> ProductDetails | None:
        """模型传入的 id 对应的完整记录，id 不存在时返回 None。
        family 商品的 ``variants`` 包含其可购买的变体记录，
        这些记录连同 family 本身都会进入会话的溯源。变体的 id 返回该变体。"""

    # ── 购物车 ──────────────────────────────────────────────────────

    @abstractmethod
    async def get_cart(self, session: ShoppingSessionContext) -> Cart:
        """当前会话的购物车，没有商品时返回空购物车。"""

    @abstractmethod
    async def add_to_cart(
        self, session: ShoppingSessionContext, product_id: str, quantity: int
    ) -> Cart:
        """将 ``quantity`` 件商品加入购物车；数量已经被截断到 ``max_quantity_per_item``
        以内。id 只能是没有 ``options`` 的普通商品或变体，不能是 family 商品；
        执行器会拦截 family 并引导模型选择变体。"""

    @abstractmethod
    async def update_cart_item(
        self, session: ShoppingSessionContext, product_id: str, quantity: int
    ) -> Cart:
        """将某行的数量设为 ``quantity``（1 到 ``max_quantity_per_item``）。
        购物车里没有的商品不做任何改动。"""

    @abstractmethod
    async def remove_from_cart(self, session: ShoppingSessionContext, product_id: str) -> Cart:
        """移除一行。购物车里没有的商品不做任何改动。"""
