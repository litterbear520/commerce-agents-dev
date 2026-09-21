"""两个角色共用的 Messages API 轮次循环零件：读对话（最近用户文本、
记忆提取读取的交互片段、压缩）、跑一轮（StreamedRound、即时分派、
展示关闭判断）、记录结果（事件、tool_result 块、用量、模型调用日志）。
``host_texts`` 标记运行时自己以 user 角色追加的消息（提醒），
它们不算用户的话。
"""
# 项目中对应 commerce-common/commerce_common/turn.py

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import (
    AsyncIterator,
    Awaitable,
    Callable,
    Collection,
    Iterable,
    Iterator,
    Mapping,
)
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from .presentation import CHIPS_TOOL, PresentationComponent, enrich_partial
from .streaming import AgentEvent, ToolOutcome, parse_partial_json

logger = logging.getLogger(__name__)

# 工具结果超过这个长度，trace 里只显示 "ok" 加一个截断摘要
_SUMMARY_MAX_CHARS = 200
_EXCERPT_MAX_CHARS = 1200
CLEARED_RESULT = "[早期轮次的结果已清除；如果需要，请重新调用该工具]"
# 流式传输过程中参数不是合法 JSON 的工具调用，用这段文本作为结果
UNREADABLE_INPUT_TEXT = "本次调用的参数不是合法 JSON，未执行。请重新发送。"


# ── 对话读取 ──────────────────────────────────────────────────


def _text_blocks(content: Any) -> list[str]:
    if isinstance(content, str):
        return [content]
    if not isinstance(content, list):
        return []
    return [
        str(block.get("text", ""))
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    ]


def _is_user_text(message: dict[str, Any], host_texts: Collection[str]) -> bool:
    if message.get("role") != "user":
        return False
    texts = _text_blocks(message.get("content"))
    return bool(texts) and not all(text in host_texts for text in texts)


def latest_user_text(messages: list[dict[str, Any]], host_texts: Collection[str] = ()) -> str:
    """最近一条用户写的文本；没有时返回空串。"""
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = message.get("content")
        texts = _text_blocks(content)
        if texts and all(text in host_texts for text in texts):
            continue
        if texts:
            return "\n".join(texts)
        # tool_result 消息是循环自己追加的，跳过继续往前找
        if isinstance(content, list) and any(
            isinstance(block, dict) and block.get("type") == "tool_result" for block in content
        ):
            continue
        return ""
    return ""


def latest_exchange(
    messages: list[dict[str, Any]], host_texts: Collection[str] = ()
) -> list[dict[str, Any]]:
    """从最近一条用户写的消息开始到末尾的切片：记忆提取只读这一轮，
    避免把之前轮次已经提取过的内容重复提取。"""
    for index in range(len(messages) - 1, -1, -1):
        if _is_user_text(messages[index], host_texts):
            return messages[index:]
    return messages


def transcript_text(messages: list[dict[str, Any]], host_texts: Collection[str] = ()) -> str:
    """把消息列表变成 ``role: text`` 的纯文本行；
    工具块和运行时追加的消息被过滤掉。"""
    lines = []
    for message in messages:
        role = message.get("role", "")
        for text in _text_blocks(message.get("content")):
            if text and text not in host_texts:
                lines.append(f"{role}: {text}")
    return "\n".join(lines)


# ── 会话标记 ──────────────────────────────────────────────────


def session_tag(session_id: str | None) -> str:
    """日志里代替原始 session_id 的标记：SHA-256 前 12 位十六进制。
    同一个会话的日志行能关联起来，但读日志的人无法反推原始 ID。"""
    return hashlib.sha256(session_id.encode()).hexdigest()[:12] if session_id else "-"


# ── 用量与日志 ────────────────────────────────────────────────


def usage_totals() -> dict[str, int]:
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }


def call_usage(response: Any) -> dict[str, int]:
    """``response.usage`` 的四个计数器；StreamedRound 也算一个。"""
    usage = getattr(response, "usage", None)
    return {key: getattr(usage, key, 0) or 0 for key in usage_totals()}


def accumulate_usage(totals: dict[str, int], response: Any) -> None:
    for key, count in call_usage(response).items():
        totals[key] += count


def prompt_tokens(response: Any) -> int:
    """一次调用的提示词大小：新输入 + 缓存读取 + 缓存写入。"""
    return sum(count for key, count in call_usage(response).items() if key != "output_tokens")


def elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def log_model_call(
    caller: logging.Logger,
    request: dict[str, Any],
    response: Any,
    started: float,
    session_id: str | None,
    **ids: Any,
) -> None:
    """每次模型调用写入的日志记录：INFO 级别记用量和耗时，
    DEBUG 级别记请求和响应体。"""
    tags = " ".join(
        f"{key}={value}" for key, value in {"session": session_tag(session_id), **ids}.items()
    )
    usage = call_usage(response)
    caller.info(
        "model call %s model=%s stop=%s input=%d cache_read=%d cache_write=%d output=%d elapsed_ms=%d",
        tags,
        request.get("model"),
        getattr(response, "stop_reason", None),
        usage["input_tokens"],
        usage["cache_read_input_tokens"],
        usage["cache_creation_input_tokens"],
        usage["output_tokens"],
        elapsed_ms(started),
        stacklevel=2,
    )
    if caller.isEnabledFor(logging.DEBUG):
        caller.debug("model request %s %s", tags, json.dumps(request, default=str), stacklevel=2)
        body = (
            response.model_dump_json()
            if hasattr(response, "model_dump_json")
            else json.dumps({"content": response.blocks, "abandoned": True}, default=str)
        )
        caller.debug("model response %s %s", tags, body, stacklevel=2)


# ── 预取辅助 ──────────────────────────────────────────────────


async def fetched(coro: Any) -> Any:
    """await 一个预取协程；失败时只 WARNING 不中断，返回 None，
    让对话轮次在没有这个数据的情况下继续。"""
    if coro is None:
        return None
    name = getattr(coro, "__qualname__", type(coro).__name__)
    try:
        return await coro
    except Exception:
        logger.warning("prefetch %s failed and the turn continues without it", name, exc_info=True)
        return None


# ── 历史压缩 ──────────────────────────────────────────────────


def compact_history(
    messages: list[dict[str, Any]], last_prompt_tokens: int, max_tokens: int, session_id: str
) -> int:
    """当最后一次调用的提示词 token 数超过 ``max_tokens`` 时，
    从最老的 tool_result 开始替换为 CLEARED_RESULT，直到总大小减半。
    来源记录在 session state 上，门控检查的内容不会被清除。"""
    if not max_tokens or last_prompt_tokens < max_tokens:
        return 0
    size = len(json.dumps(messages))
    target = size // 2
    cleared = 0
    results = (
        block
        for message in messages
        if isinstance(message.get("content"), list)
        for block in message["content"]
        if block.get("type") == "tool_result" and isinstance(block.get("content"), str)
    )
    for block in results:
        if size <= target:
            break
        if len(block["content"]) > len(CLEARED_RESULT):
            size -= len(block["content"]) - len(CLEARED_RESULT)
            block["content"] = CLEARED_RESULT
            cleared += 1
    logger.info(
        "history compacted session=%s prompt_tokens=%d results_cleared=%d",
        session_tag(session_id),
        last_prompt_tokens,
        cleared,
    )
    return cleared


# ── 即时分派 ──────────────────────────────────────────────────


class EagerDispatcher:
    """流式传输中即时启动工具执行。当一个 tool_use 块在 content_block_stop
    时参数解析成功，立刻启动执行，不等同一个响应中其他工具块流完。
    ``collect`` 是流结束后的 join：已启动的等结果，遗漏的现场执行。
    ``cancel`` 是错误和格式异常的兜底——已启动的任务不能比它的轮次活得更久。"""

    def __init__(
        self, execute: Callable[[str, dict[str, Any]], Awaitable[ToolOutcome]], enabled: bool
    ) -> None:
        self._execute = execute
        self._enabled = enabled
        self._tasks: dict[str, asyncio.Future[ToolOutcome]] = {}

    def started(self, tool_use_id: str) -> bool:
        return tool_use_id in self._tasks

    def dispatch(self, name: str, tool_use_id: str, args: dict[str, Any] | None) -> bool:
        """启动执行；返回 False 表示没启动（分派关闭、已启动、或参数无法解析），
        join 时再执行。"""
        if not self._enabled or args is None or tool_use_id in self._tasks:
            return False
        self._tasks[tool_use_id] = asyncio.ensure_future(self._execute(name, args))
        return True

    def settle(self, tool_use_id: str, outcome: ToolOutcome) -> None:
        """给一个参数未能解析的工具调用直接设置结果，不执行它。
        已启动的调用保留自己的任务。"""
        if tool_use_id in self._tasks:
            return
        settled: asyncio.Future[ToolOutcome] = asyncio.get_running_loop().create_future()
        settled.set_result(outcome)
        self._tasks[tool_use_id] = settled

    async def collect(self, tool_uses: list[Any]) -> list[ToolOutcome]:
        return await asyncio.gather(
            *(
                self._tasks[block.id]
                if block.id in self._tasks
                else self._execute(block.name, dict(block.input or {}))
                for block in tool_uses
            )
        )

    def cancel(self) -> None:
        for task in self._tasks.values():
            task.cancel()


# ── 流式跟踪 ──────────────────────────────────────────────────


@dataclass
class StreamedTool:
    """一轮中一个工具块的流式状态。``server`` 标记服务端工具（web search），
    它的输入只记录不分派；``signature`` 是上一帧 ui_partial 的去重 key。"""

    name: str
    id: str
    server: bool = False
    buffer: str = ""
    closed: bool = False
    signature: str | None = None

    def parsed(self) -> dict[str, Any] | None:
        """缓冲的输入是完整 JSON 时返回 dict，否则 None。"""
        try:
            args = json.loads(self.buffer) if self.buffer.strip() else {}
        except ValueError:
            return None
        return args if isinstance(args, dict) else None


@dataclass
class StreamedRound:
    """一轮流式响应中的全部内容块，以及它们在传输过程中产生的事件（通过 relay）。

    工具输入如果不是合法 JSON，SDK 的流累加器会抛 ValueError 中断；
    这时 ``abandoned`` 为 True，``salvaged()`` 从已到达的内容中恢复，
    让对话继续。``usage`` 是这轮流自己的计数，abandoned 的轮次也计入。
    前四个字段配置渐进预览帧：展示组件规格、可预览的工具名、
    session state、以及是否每次变化都发帧。"""

    specs: Mapping[str, PresentationComponent] = field(default_factory=dict)
    partial_tools: Collection[str] = ()
    state: Any = None
    eager_frames: bool = False
    blocks: list[dict[str, Any]] = field(default_factory=list)
    tools: dict[int, StreamedTool] = field(default_factory=dict)
    usage: SimpleNamespace = field(default_factory=lambda: SimpleNamespace(**usage_totals()))
    # abandoned 轮次在模型调用日志里报告的 stop_reason。
    stop_reason: str = "abandoned"
    abandoned: bool = False

    def feed(self, raw: Any) -> StreamedTool | None:
        """消化一个原始流事件；返回它涉及的工具（如果有的话）。"""
        raw_type = getattr(raw, "type", "")
        if raw_type in ("message_start", "message_delta"):
            # 流的计数器是累积值，每次用最新值覆盖。
            counts = getattr(raw.message if raw_type == "message_start" else raw, "usage", None)
            for key in usage_totals():
                if isinstance(value := getattr(counts, key, None), int):
                    setattr(self.usage, key, value)
            return None
        index = getattr(raw, "index", None)
        if not isinstance(index, int):
            return None
        if raw_type == "content_block_start":
            block = raw.content_block
            entry = dict(block.model_dump(exclude_none=True, exclude={"citations"}))
            kind = entry.get("type")
            # 流式字段在这里初始化为空，后续由 delta 事件逐步填充。
            if kind == "text":
                entry["text"] = ""
            elif kind == "thinking":
                entry["thinking"] = ""
            elif kind in ("tool_use", "server_tool_use"):
                entry["input"] = {}
                self.tools[index] = StreamedTool(
                    name=block.name, id=block.id, server=kind == "server_tool_use"
                )
            self.blocks.append(entry)
            return self.tools.get(index)
        if raw_type == "content_block_delta":
            delta = raw.delta
            delta_type = getattr(delta, "type", "")
            if (tool := self.tools.get(index)) is not None:
                if delta_type == "input_json_delta":
                    tool.buffer += delta.partial_json
                return tool
            entry = self.blocks[index] if index < len(self.blocks) else {}
            if delta_type == "text_delta":
                entry["text"] = entry.get("text", "") + delta.text
            elif delta_type == "thinking_delta":
                entry["thinking"] = entry.get("thinking", "") + delta.thinking
            elif delta_type == "signature_delta":
                entry["signature"] = delta.signature
            return None
        if raw_type == "content_block_stop" and (tool := self.tools.get(index)) is not None:
            tool.closed = True
            if tool.server and (args := tool.parsed()) is not None:
                self.blocks[index]["input"] = args
            return tool
        return None

    def tool_open(self) -> bool:
        """有工具的输入正在流式传输中——SDK 累加器可能抛异常的唯一状态。"""
        return any(not tool.closed for tool in self.tools.values())

    def frame(self, tool: StreamedTool) -> AgentEvent | None:
        """工具最新输入 delta 后的 ui_partial 事件，或 None。
        默认只在结构变化时发帧（新字段、新数组元素），不发半截字符串；
        ``eager_frames`` 时每次可见变化都发，文本随生成逐渐变长。"""
        if tool.name not in self.partial_tools:
            return None
        parsed = parse_partial_json(tool.buffer, settle_strings=not self.eager_frames)
        partial = enrich_partial(self.specs[tool.name], parsed, self.state) if parsed else None
        if partial is None:
            return None
        component, payload, signature = partial
        key = json.dumps(payload if self.eager_frames else signature, sort_keys=True, default=str)
        if key == tool.signature:
            return None
        tool.signature = key
        return AgentEvent.ui_partial(component, payload, tool.id)

    async def relay(
        self,
        stream: Any,
        dispatcher: EagerDispatcher,
        announce: Callable[[str, str, dict[str, Any]], AgentEvent],
    ) -> AsyncIterator[AgentEvent]:
        """消化 ``stream`` 的每个原始事件，yield 途中产生的事件：
        文本 delta、预览帧、以及即时分派启动时的 tool_call 事件。
        只捕获 SDK 对未完成工具输入的拒绝（ValueError）——
        轮次标记为 abandoned；预览钩子的异常原样传播。"""
        events = aiter(stream)
        while True:
            try:
                raw = await anext(events)
            except StopAsyncIteration:
                return
            except ValueError:
                if not self.tool_open():
                    raise
                self.abandoned = True
                return
            tool = self.feed(raw)
            raw_type = getattr(raw, "type", "")
            if raw_type == "content_block_delta":
                delta = raw.delta
                if getattr(delta, "type", "") == "text_delta" and delta.text:
                    yield AgentEvent.text_delta(delta.text)
                elif tool is not None and (frame := self.frame(tool)) is not None:
                    yield frame
            elif raw_type == "content_block_stop" and tool is not None and not tool.server:
                args = tool.parsed()
                if dispatcher.dispatch(tool.name, tool.id, args):
                    yield announce(tool.name, tool.id, args or {})

    def salvaged(self) -> tuple[dict[str, Any] | None, list[Any], set[str]]:
        """从中断的流中恢复：返回助手消息、工具调用列表、以及输入无法解析的调用 ID。"""
        unreadable: set[str] = set()
        tool_uses: list[Any] = []
        for index, entry in enumerate(self.blocks):
            if (tool := self.tools.get(index)) is None:
                continue
            parsed = tool.parsed() if tool.closed else None
            if parsed is not None:
                entry["input"] = parsed
            else:
                unreadable.add(tool.id)
            if not tool.server:
                tool_uses.append(SimpleNamespace(name=tool.name, id=tool.id, input=entry["input"]))
        content = [entry for entry in self.blocks if entry.get("type") != "text" or entry["text"]]
        message = {"role": "assistant", "content": content} if content else None
        return message, tool_uses, unreadable


# ── 恢复辅助 ──────────────────────────────────────────────────


def salvage_round(
    streamed: StreamedRound,
    dispatcher: EagerDispatcher,
    caller: logging.Logger,
    session_id: str | None,
    round_index: int,
) -> tuple[dict[str, Any] | None, list[Any], set[str]]:
    """对 SDK 累加器 abandoned 的轮次调用 salvaged()，
    把每个无法解析的客户端调用在 dispatcher 上 settle 为错误结果，
    让模型重新发送。"""
    reply, tool_uses, unreadable = streamed.salvaged()
    for tool in streamed.tools.values():
        if tool.id not in unreadable:
            continue
        caller.warning(
            "tool input unreadable session=%s round=%d tool=%s id=%s chars=%d",
            session_tag(session_id),
            round_index,
            tool.name,
            tool.id,
            len(tool.buffer),
            stacklevel=2,
        )
        if not tool.server:
            dispatcher.settle(tool.id, ToolOutcome.error(UNREADABLE_INPUT_TEXT))
    return reply, tool_uses, unreadable


# ── 轮次辅助 ──────────────────────────────────────────────────


def assistant_message(final: Any) -> dict[str, Any] | None:
    """正常结束的响应转成消息 dict；空内容时返回 None。"""
    content = [
        block.model_dump(exclude_none=True, exclude={"citations"}) for block in final.content
    ]
    return {"role": "assistant", "content": content} if content else None


def outcome_events(tool: str, tool_use_id: str, outcome: ToolOutcome) -> Iterator[AgentEvent]:
    """一个工具调用结果的事件序列：先是 outcome 自身的事件（ui 事件加上调用 ID），
    然后是 tool_result 事件。"""
    for event in outcome.events:
        if event.type == "ui":
            event.data = {**event.data, "stream_id": tool_use_id}
        yield event
    keep_text = outcome.refused or len(outcome.result_text) < _SUMMARY_MAX_CHARS
    yield AgentEvent.tool_result(
        tool,
        tool_use_id,
        outcome.result_text if keep_text else "ok",
        outcome.is_error,
        status="blocked" if outcome.blocked else None,
        reason=outcome.blocked,
        excerpt=None if keep_text else outcome.result_text[:_EXCERPT_MAX_CHARS],
    )


def round_closes_turn(
    calls: Iterable[tuple[str, ToolOutcome]], clean: Callable[[str, ToolOutcome], bool]
) -> bool:
    """当一轮可以不用再让模型说话就直接结束时返回 True：
    建议按钮工具成功了，而且每个调用都是 clean 的
    （展示类调用，没有被拒绝、拦截或标注）。"""
    calls = list(calls)
    return any(name == CHIPS_TOOL for name, _ in calls) and all(clean(*call) for call in calls)


def tool_result_block(tool_use_id: str, outcome: ToolOutcome) -> dict[str, Any]:
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": outcome.result_text,
        "is_error": outcome.is_error,
    }


# ── 中断修复 ──────────────────────────────────────────────────


INTERRUPTED_RESULT_TEXT = "本轮在该调用返回之前中断了；如果仍然需要，请重新调用。"


def close_open_tool_uses(
    messages: list[dict[str, Any]], settled: Mapping[str, ToolOutcome] | None = None
) -> int:
    """如果对话以一条助手消息结尾，且其中的 tool_use 块没有对应的 tool_result，
    追加结果让对话格式合法：有真实结果的用真实结果（写操作完成了就报完成，
    不让模型重试），否则用中断错误。返回追加的结果数。"""
    if not messages or messages[-1].get("role") != "assistant":
        return 0
    content = messages[-1].get("content")
    if not isinstance(content, list):
        return 0
    ids = [
        (block.get("id") if isinstance(block, dict) else getattr(block, "id", None))
        for block in content
        if (block.get("type") if isinstance(block, dict) else getattr(block, "type", None))
        == "tool_use"
    ]
    if not ids:
        return 0
    settled = settled or {}
    messages.append(
        {
            "role": "user",
            "content": [
                tool_result_block(tool_use_id, settled[tool_use_id])
                if tool_use_id in settled
                else {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": INTERRUPTED_RESULT_TEXT,
                    "is_error": True,
                }
                for tool_use_id in ids
            ],
        }
    )
    return len(ids)
