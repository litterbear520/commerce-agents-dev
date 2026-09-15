"""按预录剧本返回响应的假客户端，用于零 API 调用的单元测试和集成测试。
FakeClient 回放 messages.stream；每次调用的参数记录在 calls 里，
剧本用完后抛异常让测试失败而不是挂起。"""

from __future__ import annotations

import json
from collections.abc import Iterable
from types import SimpleNamespace
from typing import Any

# ── 内容块 ─────────────────────────────────────────────────────────────

# 真实 API 的 content block 支持属性访问（block.type）和 model_dump()。
# FakeBlock 用最少的代码模拟这两个能力。


class FakeBlock:
    """模拟 SDK 内容块：支持属性访问和 model_dump。"""

    def __init__(self, **fields: Any) -> None:
        self._fields = fields
        for key, value in fields.items():
            setattr(self, key, value)

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        del kwargs
        return dict(self._fields)


def text_block(text: str) -> FakeBlock:
    return FakeBlock(type="text", text=text)


def tool_use_block(name: str, tool_input: dict[str, Any], block_id: str = "tu-1") -> FakeBlock:
    return FakeBlock(type="tool_use", id=block_id, name=name, input=tool_input)


# ── 用量占位 ───────────────────────────────────────────────────────────


def _usage() -> SimpleNamespace:
    return SimpleNamespace(
        input_tokens=1, output_tokens=1, cache_read_input_tokens=0, cache_creation_input_tokens=0
    )


# ── 响应构造器 ─────────────────────────────────────────────────────────

# 用内容块拼出完整的"模型一轮回复"。
# stop_reason 告诉调用方这轮结束了还是要调工具。


def text_message(text: str) -> SimpleNamespace:
    """模型说完话、结束这轮对话的消息。"""
    return SimpleNamespace(stop_reason="end_turn", usage=_usage(), content=[text_block(text)])


def tool_use_message(name: str, tool_input: dict[str, Any]) -> SimpleNamespace:
    """模型请求调用一个工具的消息。"""
    return tool_calls_message((name, tool_input))


def tool_calls_message(*calls: tuple[Any, ...]) -> SimpleNamespace:
    """模型一次请求调用多个工具的消息。每个 call 是 (name, input) 或 (name, input, block_id)。"""
    content = [
        tool_use_block(call[0], call[1], call[2] if len(call) > 2 else f"tu-{index + 1}")
        for index, call in enumerate(calls)
    ]
    return SimpleNamespace(stop_reason="tool_use", usage=_usage(), content=content)


def create_response(*blocks: FakeBlock, stop_reason: str = "tool_use") -> SimpleNamespace:
    """messages.create 的返回值：内容块 + stop_reason + 用量。"""
    return SimpleNamespace(content=list(blocks), stop_reason=stop_reason, usage=_usage())


# ── 假流 ──────────────────────────────────────────────────────────────

# 真实 API 的流式调用逐个发送事件（start → delta → stop）。
# FakeStream 把一个完整响应自动拆成同样的事件序列。

# chunks: 指定某个块的工具参数分几段到达（模拟真实流式的 JSON 分片）
Chunks = dict[int, list[str | BaseException]]


class FakeStream:
    """把一个完整响应拆成流式事件序列。"""

    # 每个块先发 content_block_start，再发 delta（文本或工具参数 JSON），
    # 最后发 content_block_stop。

    def __init__(self, final: SimpleNamespace, chunks: Chunks | None = None) -> None:
        self._final = final
        self._chunks = chunks or {}

    async def __aenter__(self) -> FakeStream:
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    def __aiter__(self):
        async def events():
            usage = getattr(self._final, "usage", None)
            if usage is not None:
                yield SimpleNamespace(type="message_start", message=SimpleNamespace(usage=usage))
            for index, block in enumerate(self._final.content):
                yield SimpleNamespace(type="content_block_start", index=index, content_block=block)
                block_type = getattr(block, "type", None)
                if block_type == "text":
                    delta = SimpleNamespace(type="text_delta", text=block.text)
                    yield SimpleNamespace(type="content_block_delta", index=index, delta=delta)
                elif block_type == "tool_use":
                    for piece in self._chunks.get(index, [json.dumps(block.input or {})]):
                        if isinstance(piece, BaseException):
                            raise piece
                        delta = SimpleNamespace(type="input_json_delta", partial_json=piece)
                        yield SimpleNamespace(type="content_block_delta", index=index, delta=delta)
                yield SimpleNamespace(type="content_block_stop", index=index)
            if usage is not None:
                yield SimpleNamespace(type="message_delta", usage=usage)

        return events()

    async def get_final_message(self) -> SimpleNamespace:
        return self._final


# ── 假客户端 ──────────────────────────────────────────────────────────

# 按预录剧本依次返回响应。每次调用的参数记录在 calls 里，
# 剧本用完后抛异常让测试失败而不是挂起。


class FakeClient:
    """按剧本回放 messages.stream 的假客户端。chunks 只作用于第一次调用。"""

    def __init__(self, responses: Iterable[SimpleNamespace], chunks: Chunks | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._responses = list(responses)
        self._chunks = chunks
        self.messages = SimpleNamespace(stream=self._stream)

    def _stream(self, **kwargs: Any) -> FakeStream:
        self.calls.append(kwargs)
        if not self._responses:
            raise AssertionError("剧本用完了，但代码还在调用模型")
        return FakeStream(self._responses.pop(0), self._chunks if len(self.calls) == 1 else None)
