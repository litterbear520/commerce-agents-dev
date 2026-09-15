"""购物 agent 的数据模型：后端返回的数据结构，以及门控和信息补全所用的会话记录。"""
# 项目中对应 shopping-agent/core/shopping_agent/types.py
# 当前只包含到 Step 06 用到的类型，Order / Policy 等到 Step 13 再加

from __future__ import annotations

from typing import Literal, TypeVar

from pydantic import BaseModel, Field

# ── 溯源记录容量 ─────────────────────────────────────────────────────
# 项目中对应 commerce_common/types.py 的 PROVENANCE_CAP + remember()
# 后续 Step 17 把共享模块迁到 commerce_common 时再拆出去

RecordT = TypeVar("RecordT")

PROVENANCE_CAP = 200  # seen_products 字典最多保留多少条，超出时淘汰最早插入的


def remember(records: dict[str, RecordT], key: str, value: RecordT) -> None:
    # 先 pop 再插，让同一个 key 刷新到字典末尾（Python 3.7+ 字典有序）
    records.pop(key, None)
    records[key] = value
    while len(records) > PROVENANCE_CAP:
        del records[next(iter(records))]


# ── 商品 ─────────────────────────────────────────────────────────────


class Product(BaseModel):
    """一条商品目录记录，有三种形态。

    plain：直接购买。family：带有 ``options``（每个选项和它的可选值），
    搜索会返回它但购物车拒绝它；它的 ``price`` 是最低有货变体的价格，
    ``in_stock`` 在任意变体有货时为 True。variant：出现在 family 的
    ``ProductDetails.variants`` 列表中，有自己的 id、价格和库存，
    ``option_values``（每个选项对应一个值），以及 family 的 id ``variant_of``；
    购物车接受它的 id。只有列出的变体存在。
    """

    product_id: str
    title: str
    brand: str | None = None
    price: float
    currency: str = "USD"
    rating: float | None = Field(default=None, ge=0, le=5)
    review_count: int | None = None
    image_url: str | None = None
    category: str | None = None
    labels: list[str] = Field(default_factory=list)
    attributes: dict[str, str] = Field(default_factory=dict)
    in_stock: bool = True
    short_description: str | None = None
    options: dict[str, list[str]] = Field(default_factory=dict)
    option_values: dict[str, str] = Field(default_factory=dict)
    variant_of: str | None = None

    @property
    def has_options(self) -> bool:
        """family 商品返回 True：购物车只接受它的变体。"""
        return bool(self.options)


class ProductDetails(Product):
    # 商品详情：比 Product 多长描述、规格参数、评价摘要和变体列表

    long_description: str | None = None
    specs: dict[str, str] = Field(default_factory=dict)
    review_highlights: list[str] = Field(default_factory=list)
    variants: list[Product] = Field(default_factory=list)


class SearchFilters(BaseModel):
    # 搜索过滤条件

    category: str | None = None
    min_price: float | None = None
    max_price: float | None = None
    min_rating: float | None = None
    attributes: dict[str, str] = Field(default_factory=dict)
    sort: Literal["relevance", "price_asc", "price_desc", "rating"] = "relevance"


# ── 购物车 ───────────────────────────────────────────────────────────


class CartItem(BaseModel):
    """``quantity`` 按整件计数（一件、一晚、一个座位）。"""

    product_id: str
    title: str
    price: float
    quantity: int = Field(ge=1)
    image_url: str | None = None
    option_values: dict[str, str] = Field(default_factory=dict)
    variant_of: str | None = None

    @property
    def line_total(self) -> float:
        return round(self.price * self.quantity, 2)


class Cart(BaseModel):
    items: list[CartItem] = Field(default_factory=list)
    currency: str = "USD"

    @property
    def item_count(self) -> int:
        return sum(item.quantity for item in self.items)

    @property
    def subtotal(self) -> float:
        return round(sum(item.line_total for item in self.items), 2)


# ── 会话上下文与状态 ─────────────────────────────────────────────────


class ShoppingSessionContext(BaseModel):
    # 项目中继承 ClockContext（带时区和 now），Step 17 迁到 commerce_common 时再加

    session_id: str
    user_id: str


class ShoppingSessionState(BaseModel):
    """服务端为每个会话维护的状态。``seen_products`` 是溯源记录：
    购物车写操作只接受其中的 id，展示型工具调用时从中补全商品信息。"""

    seen_products: dict[str, Product] = Field(default_factory=dict)

    def remember_products(self, products: list[Product]) -> None:
        for product in products:
            remember(self.seen_products, product.product_id, product)
