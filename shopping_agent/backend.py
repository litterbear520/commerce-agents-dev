"""StorefrontBackend 接口：采用方唯一需要实现的对接接口，
将每个方法映射到自己的商品目录、购物车等服务。
这些方法返回的所有内容都会经过围栏处理后才到达模型（fencing.py）。
"""
# 项目中对应 shopping-agent/core/shopping_agent/backend.py

from __future__ import annotations

from abc import ABC, abstractmethod

from .types import (
    Cart,
    CheckoutHandoff,
    FulfillmentOption,
    Order,
    Policy,
    Product,
    ProductDetails,
    SearchFilters,
    ShoppingSessionContext,
    UserPreferences,
)


class NotOffered(Exception):  # 执行器转达的一个信号，不是故障
    """后端方法抛出此异常表示当前商品或场景不提供该服务
    （例如某个卖家不支持配送），而不是系统故障。
    执行器会告诉模型"该店不提供此服务"。"""


class Unavailable(Exception):  # 和 NotOffered 一样转达，措辞不同
    """``add_to_cart`` 抛出此异常表示商品存在但当前无法购买（缺货等）。
    消息只包含 id：哪个商品不可用，以及（如果是变体的话）哪些同级变体有货。
    执行器会转达给模型，购物车不做任何写入。"""


class StorefrontBackend(ABC):
    """每个方法代表 ``session`` 中的顾客操作，在服务端用它为会话持有的凭证调用对应系统的
    API；模型只看到方法的返回结果，看不到凭证。购物车方法是唯一的写操作；每次写入都
    经过执行器的溯源门控和数量上限（gates.py），并返回完整购物车，后端仍需在自己这边
    原子地执行业务规则（资格、库存、限额），因为执行器的锁只覆盖单进程内的会话。
    没有任何方法会下单或转账：``checkout`` 只是把购物车渲染出来交给调用方完成。
    :class:`NotOffered` 到模型那里是「本店不提供」；其他任何异常都是工具暂时不可用，
    由执行器记录日志。
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
        """当前会话的购物车，没有商品时返回空购物车。每轮开始前、购物车门控
        和 ``checkout`` 都会读它。"""

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

    # ── 用户上下文 ────────────────────────────────────────────────

    @abstractmethod
    async def get_preferences(self, session: ShoppingSessionContext) -> UserPreferences:
        """当前顾客的偏好信息（含访客）。每轮开始前读取；模型不会写入。"""

    # ── 订单与政策 ──────────────────────────────────────────────────

    @abstractmethod
    async def get_orders(self, session: ShoppingSessionContext, limit: int = 5) -> list[Order]:
        """当前顾客的订单，按时间倒序，最多 ``limit`` 条。
        订单中的商品会进入溯源记录，重新购买无需再搜索。"""

    @abstractmethod
    async def get_order(self, session: ShoppingSessionContext, order_id: str) -> Order | None:
        """查看顾客的一张订单，id 不存在或不属于该顾客时返回 None。"""

    @abstractmethod
    async def search_policies(self, session: ShoppingSessionContext, query: str) -> list[Policy]:
        """按关键词搜索帮助和政策文档；没有匹配时返回空列表。"""

    # ── 履约 ────────────────────────────────────────────────────────

    @abstractmethod
    async def get_fulfillment_options(
        self, session: ShoppingSessionContext, product_ids: list[str]
    ) -> list[FulfillmentOption]:
        """模型传入的最多 20 个 id 的配送、自提和发货选项；
        目录中不存在的 id 被忽略。"""

    # ── 结账交接 ────────────────────────────────────────────────────

    async def checkout_handoff(
        self, session: ShoppingSessionContext, cart: Cart
    ) -> list[CheckoutHandoff]:
        """可选：这个购物车在哪里完成付款——平台的托管结账 URL，
        或者多卖家市场里每个卖家一条。URL 由后端填充、调用方渲染，
        模型看不到也不需要传递。默认返回空列表，调用方用自己的结账流程。"""
        return []
