"""agent 轮次产出的事件流，以及每个工具调用的结果类型。

调用方按类型渲染事件，忽略不认识的类型。
"""
# 项目中对应 commerce-common/commerce_common/streaming.py
# 当前只包含 AgentEvent / ToolOutcome / to_sse
# parse_partial_json（流式工具输入解析）到 Step 15 再加
# 展示层的 run_presentation() 返回 ToolOutcome，里面带一个 ui 事件

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field

EventType = Literal[
    "text_delta",
    "tool_call",
    "tool_result",
    "ui",
    "ui_partial",
    "cart_update",
    "change_update",
    "progress",
    "turn_complete",
    "error",
]


class AgentEvent(BaseModel):
    type: EventType
    data: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def text_delta(cls, text: str) -> AgentEvent:
        return cls(type="text_delta", data={"text": text})

    @classmethod
    def tool_call(
        cls,
        tool: str,
        tool_use_id: str,
        input_data: dict[str, Any],
        label: str | None = None,
    ) -> AgentEvent:
        data: dict[str, Any] = {"tool": tool, "id": tool_use_id, "input": input_data}
        if label:
            data["label"] = label
        return cls(type="tool_call", data=data)

    @classmethod
    def tool_result(
        cls,
        tool: str,
        tool_use_id: str,
        summary: str,
        is_error: bool = False,
        status: str | None = None,
        reason: str | None = None,
        excerpt: str | None = None,
    ) -> AgentEvent:
        data: dict[str, Any] = {
            "tool": tool,
            "id": tool_use_id,
            "summary": summary,
            "is_error": is_error,
            "status": status or ("error" if is_error else "ok"),
        }
        if reason:
            data["reason"] = reason
        if excerpt is not None:
            data["excerpt"] = excerpt
        return cls(type="tool_result", data=data)

    @classmethod
    def ui(cls, component: str, payload: dict[str, Any]) -> AgentEvent:
        return cls(type="ui", data={"component": component, "payload": payload})

    @classmethod
    def ui_partial(cls, component: str, payload: dict[str, Any], stream_id: str) -> AgentEvent:
        return cls(
            type="ui_partial",
            data={"component": component, "payload": payload, "stream_id": stream_id},
        )

    @classmethod
    def cart_update(cls, cart: dict[str, Any]) -> AgentEvent:
        return cls(type="cart_update", data={"cart": cart})

    @classmethod
    def change_update(cls, change: dict[str, Any]) -> AgentEvent:
        return cls(type="change_update", data={"change": change})

    @classmethod
    def progress(cls, message: str, tool: str | None = None, step: int | None = None) -> AgentEvent:
        data: dict[str, Any] = {"message": message}
        if tool:
            data["tool"] = tool
        if step is not None:
            data["step"] = step
        return cls(type="progress", data=data)

    @classmethod
    def turn_complete(
        cls,
        stop_reason: str | None,
        usage: dict[str, int],
        elapsed_ms: int,
        results_cleared: int,
    ) -> AgentEvent:
        return cls(
            type="turn_complete",
            data={
                "stop_reason": stop_reason,
                "usage": usage,
                "elapsed_ms": elapsed_ms,
                "results_cleared": results_cleared,
            },
        )

    @classmethod
    def error(cls, message: str) -> AgentEvent:
        return cls(type="error", data={"message": message})


@dataclass
class ToolOutcome:
    """一个工具调用的产出：``result_text`` 给模型看，``events`` 给调用方渲染。
    ``blocked`` 记录拦截门控的名称；``is_error`` 标记失败。"""

    result_text: str
    events: list[AgentEvent] = field(default_factory=list)
    is_error: bool = False
    blocked: str | None = None

    @classmethod
    def error(cls, text: str) -> ToolOutcome:
        return cls(text, is_error=True)

    @classmethod
    def held(cls, gate: str, text: str) -> ToolOutcome:
        return cls(text, blocked=gate)

    @property
    def refused(self) -> bool:
        return self.is_error or self.blocked is not None


def to_sse(event: AgentEvent) -> str:
    """一帧 Server-Sent Events：``event:`` 是类型，``data:`` 是 JSON 载荷。"""
    return f"event: {event.type}\ndata: {json.dumps(event.data, ensure_ascii=False)}\n\n"
