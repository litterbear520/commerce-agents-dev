"""内置展示工具的 payload 定义：模型可以传什么。把 payload 变成门户渲染内容的补全逻辑
在 ``enrichment`` 模块。"""
# 项目中对应 merchant-agent/core/merchant_agent/tools/presentation.py
# 省略：PREVIEW_TOOL、PresentChangePreviewPayload（Step 20）

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from commerce_common.presentation import PresentationPayload


class MetricPick(BaseModel):
    """一张指标卡：模型给出指标名并加注释；数值从工具返回的结果里补全。"""

    metric: str = Field(max_length=60)
    note: str | None = Field(default=None, max_length=140)


class PresentMetricsPayload(PresentationPayload):
    title: str | None = Field(default=None, max_length=80)
    period: str | None = Field(default=None, max_length=80)
    picks: list[MetricPick] = Field(min_length=1, max_length=8)


class DigestItem(BaseModel):
    kind: Literal["low_stock", "slow_mover", "order_issue", "metric", "pending_change", "note"]
    ref_id: str | None = Field(default=None, max_length=64)
    headline: str = Field(max_length=120)
    why_it_matters: str | None = Field(default=None, max_length=160)


class PresentDigestPayload(PresentationPayload):
    title: str | None = Field(default=None, max_length=80)
    items: list[DigestItem] = Field(min_length=1, max_length=8)
