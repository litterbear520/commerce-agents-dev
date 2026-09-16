"""展示型工具的 payload 定义：模型可以传什么。

把 payload 变成调用方渲染内容的充实逻辑在 ``enrichment`` 模块。
"""
# 项目中对应 shopping-agent/core/shopping_agent/tools/presentation.py
# 当前跳过 PresentOrderStatusPayload（Step 13）和 PresentDisclosurePayload

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from commerce_common.presentation import PresentationPayload

# ── 商品展示 ────────────────────────────────────────────────────────


# 模型选的一个商品：id + 推荐理由
class ProductPick(BaseModel):
    product_id: str
    reason: str | None = Field(default=None, max_length=140)


class PresentProductsPayload(PresentationPayload):
    """模型传 ``picks``；调用方收到 ``items``，每个 pick 拼接上完整的商品记录。"""

    title: str | None = Field(default=None, max_length=80)
    layout: Literal["carousel", "grid", "list"] = "carousel"
    picks: list[ProductPick] = Field(min_length=1, max_length=12)


# ── 商品对比 ────────────────────────────────────────────────────────


# 对比表中的一行：商品 id + 优缺点 + 适合场景
class ComparisonEntry(BaseModel):
    product_id: str
    pros: list[str] = Field(default_factory=list, max_length=4)
    cons: list[str] = Field(default_factory=list, max_length=3)
    best_for: str | None = Field(default=None, max_length=80)


class PresentComparisonPayload(PresentationPayload):
    title: str | None = Field(default=None, max_length=80)
    entries: list[ComparisonEntry] = Field(min_length=2, max_length=4)
    dimensions: list[str] = Field(default_factory=list, max_length=6)
    recommended_product_id: str | None = None


# ── 购物计划 ────────────────────────────────────────────────────────


# 计划中的一步：标签 + 说明 + 关联商品
class PlanStep(BaseModel):
    label: str = Field(max_length=120)
    detail: str | None = Field(default=None, max_length=240)
    product_ids: list[str] = Field(default_factory=list, max_length=8)


class PresentPlanPayload(PresentationPayload):
    title: str = Field(max_length=80)
    intro: str | None = Field(default=None, max_length=240)
    steps: list[PlanStep] = Field(min_length=1, max_length=12)


# ── 导购指南 ────────────────────────────────────────────────────────


# 指南中的一节：标题 + 正文
class GuideSection(BaseModel):
    heading: str = Field(max_length=80)
    body: str = Field(max_length=600)


class PresentGuidePayload(PresentationPayload):
    """``related_product_ids`` 在调用方的 payload 里变成 ``related_products``。"""

    title: str = Field(max_length=80)
    sections: list[GuideSection] = Field(min_length=1, max_length=8)
    related_product_ids: list[str] = Field(default_factory=list, max_length=8)
    sources: list[str] = Field(default_factory=list, max_length=5)


# ── 结账 ────────────────────────────────────────────────────────────


class CheckoutPayload(PresentationPayload):
    """把购物车提交给调用方的结账流程；这里不产生扣款。"""

    note: str | None = Field(default=None, max_length=300)
    fulfillment_method: Literal["delivery", "pickup", "shipping"] | None = None
