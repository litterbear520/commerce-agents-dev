"""展示型工具：组件规格定义，以及验证、补全、发出 ``ui`` 事件的统一运行器。

模型负责选择和标注；组件上的每一条事实都由服务端拼接。
"""
# 项目中对应 commerce-common/commerce_common/presentation.py
# PresentationExtension 是垂直行业的扩展点（Step 28），这里先定义结构

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .fencing import sanitize_suggestion_chips
from .streaming import AgentEvent, ToolOutcome

# ── 常量 ────────────────────────────────────────────────────────────

# 两个角色里唯一携带本轮建议按钮的组件。
CHIPS_TOOL = "present_suggestions"
CHIPS_COMPONENT = "suggestions"


# ── 异常 ────────────────────────────────────────────────────────────


class PresentationRefused(ValueError):
    """补全钩子无法渲染时抛出。``gate`` 指明拦截的门控名称
    （结果变成被拦截的调用）；没有 gate 则结果是普通错误。"""

    def __init__(self, message: str, gate: str | None = None) -> None:
        super().__init__(message)
        self.gate = gate


# ── Payload 基类与建议按钮 ──────────────────────────────────────────


class PresentationPayload(BaseModel):
    """所有展示型 payload 的基类。未声明的字段直接丢弃而不是拒绝：
    工具的 input_schema 负责约束模型，多传一个字段不值得拒绝整张卡片。"""

    model_config = ConfigDict(extra="ignore")


class PresentSuggestionsPayload(PresentationPayload):
    """一轮对话的建议按钮。验证时自动清洗，全部清洗为空则拒绝——
    建议按钮的全部内容就是这些文本，空了就没意义。"""

    suggestions: list[str] = Field(min_length=1, max_length=4)

    @field_validator("suggestions", mode="after")
    @classmethod
    def _sanitize_suggestions(cls, chips: list[str]) -> list[str]:
        return sanitize_suggestion_chips(chips)

    @model_validator(mode="after")
    def _require_a_visible_chip(self) -> PresentSuggestionsPayload:
        if not self.suggestions:
            raise ValueError("清洗后所有建议都为空——请发送 1-4 条简短的纯文本建议。")
        return self


# ── 补全上下文与组件规格 ────────────────────────────────────────────


@dataclass(frozen=True)
class EnrichmentContext:
    """补全钩子的工作上下文。钩子把需要告诉模型的备注
    （比如丢弃了哪些 id、删掉了什么文本）追加到 ``notes``。"""

    backend: Any
    config: Any
    session: Any
    state: Any
    notes: list[str] = field(default_factory=list)


EnrichFn = Callable[[Any, EnrichmentContext], Awaitable[dict[str, Any]]]
PartialEnrichFn = Callable[[dict[str, Any], Any], dict[str, Any] | None]


@dataclass(frozen=True, kw_only=True)
class PresentationComponent:
    """一个展示型工具：``component`` 是调用方渲染的组件名，``payload_model``
    验证模型的参数，``enrich`` 钩子把服务端数据拼接上去。
    没有补全钩子时，验证后的 payload 直接发出。
    ``enrich_partial`` 是流式预览钩子——从不完整的参数中生成 UI 骨架。"""

    name: str
    component: str
    payload_model: type[BaseModel]
    enrich: EnrichFn | None = None
    enrich_partial: PartialEnrichFn | None = None


@dataclass(frozen=True, kw_only=True)
class PresentationExtension(PresentationComponent):
    """部署方提供的展示组件，在构造时合并到工具表面。
    ``input_schema`` 是模型看到的参数结构，
    ``description`` 是模型看到的工具说明。"""

    input_schema: dict[str, Any] = field(default_factory=dict)
    description: str = ""


# ── 运行器 ──────────────────────────────────────────────────────────


def invalid_payload_prefix(tool_name: str) -> str:
    """payload 验证失败时返回给模型的前缀，后面跟验证器的错误信息。"""
    return f"{tool_name} 参数无效："


async def run_presentation(
    spec: PresentationComponent,
    tool_input: dict[str, Any],
    context: EnrichmentContext,
    displayed_text: str,
) -> ToolOutcome:
    """验证、补全、发出一个组件。返回文本是 ``displayed_text`` 加上钩子的备注；
    ``ui`` 事件携带补全后的 payload。"""
    try:
        payload = spec.payload_model.model_validate(tool_input)
    except ValueError as exc:
        return ToolOutcome.error(f"{invalid_payload_prefix(spec.name)} {exc}")
    if spec.enrich is None:
        enriched = payload.model_dump(exclude_none=True)
    else:
        try:
            enriched = await spec.enrich(payload, context)
        except PresentationRefused as refused:
            if refused.gate is None:
                return ToolOutcome.error(str(refused))
            return ToolOutcome.held(refused.gate, str(refused))
        except ValueError as exc:
            return ToolOutcome.error(str(exc))
    text = " ".join([displayed_text, *context.notes])
    return ToolOutcome(text, events=[AgentEvent.ui(spec.component, enriched)])


# ── 流式预览 ──────────────────────────────────────────────────────────


def partial_signature(payload: dict[str, Any]) -> Any:
    """流式传输中判定「可见变化」的依据：标题是否出现，
    以及 payload 上每个列表的长度（如果列表元素带 ``products``，
    则记每个元素的 products 长度）。"""
    lists = {}
    for key, value in payload.items():
        if not isinstance(value, list):
            continue
        if value and all(isinstance(item, dict) and "products" in item for item in value):
            lists[key] = [len(item.get("products") or []) for item in value]
        else:
            lists[key] = len(value)
    return (bool(payload.get("title")), lists)


def partial_ui_tool_names(
    components: Mapping[str, PresentationComponent], extensions: Sequence[PresentationExtension]
) -> frozenset[str]:
    """编排器渐进渲染的工具名：有 ``enrich_partial`` 钩子的展示组件。"""
    specs = [*components.values(), *extensions]
    return frozenset(spec.name for spec in specs if spec.enrich_partial is not None)


def enrich_partial(
    spec: PresentationComponent, data: dict[str, Any], state: Any
) -> tuple[str, dict[str, Any], Any] | None:
    """一个还在流式传输中的调用的预览 payload 和变化签名，或 None。
    没有标题且所有列表都还是空的 payload 不算一帧。"""
    if spec.enrich_partial is None:
        return None
    payload = spec.enrich_partial(data, state)
    if payload is None:
        return None
    has_title, lists = signature = partial_signature(payload)
    if not has_title and lists and not any(lists.values()):
        return None
    return spec.component, payload, signature
