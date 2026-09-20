"""购物 agent 在 Messages API 上的轮次循环：每次迭代一轮模型调用，
工具在块关闭时即时分派，展示调用边流式边渲染，通过对话的滚动缓存断点，
一轮纯展示调用（含建议按钮）结束轮次（``close_on_presentation``）。

    agent = ShoppingAgent(backend=my_backend, skills_dir=Path("shopping-agent/skills"))
    async for event in agent.stream_turn(messages, session, state):
        ...
"""
# 项目中对应 shopping-agent/runtime-messages-api/shopping_agent_runtime/orchestrator.py
# MemoryRuntime / update_memory / memory 预取 → Step 16 接入

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any, cast

from anthropic import AsyncAnthropic

from commerce_common.grounding import first_forced_tool
from commerce_common.presentation import (
    PresentationComponent,
    PresentationExtension,
    partial_ui_tool_names,
)
from commerce_common.prompt_assembly import (
    build_request_messages,
    build_system_blocks,
    with_eager_input,
    with_tool_cache_control,
)
from commerce_common.skills import SkillRegistry
from commerce_common.streaming import AgentEvent, ToolOutcome
from commerce_common.turn import (
    EagerDispatcher,
    StreamedRound,
    accumulate_usage,
    assistant_message,
    close_open_tool_uses,
    compact_history,
    elapsed_ms,
    fetched,
    latest_user_text,
    log_model_call,
    outcome_events,
    prompt_tokens,
    round_closes_turn,
    salvage_round,
    tool_result_block,
    usage_totals,
)
from shopping_agent.backend import StorefrontBackend
from shopping_agent.config import ShoppingAgentConfig
from shopping_agent.enrichment import PRESENTATION_COMPONENTS
from shopping_agent.executor import ShoppingToolExecutor
from shopping_agent.grounding import GROUNDING_RULES
from shopping_agent.prompt import build_dynamic_context, build_static_system
from shopping_agent.tools.registry import build_tools
from shopping_agent.types import Cart, ShoppingSessionContext, ShoppingSessionState, UserPreferences

logger = logging.getLogger(__name__)


class ShoppingAgent:
    """一个部署实例。``executor_class`` 是部署方自定义
    :class:`ShoppingToolExecutor` 子类的接入点。"""

    def __init__(
        self,
        *,
        backend: StorefrontBackend,
        skills: SkillRegistry | None = None,
        skills_dir: Path | None = None,
        config: ShoppingAgentConfig | None = None,
        client: AsyncAnthropic | None = None,
        extra_presentation_tools: Sequence[PresentationExtension] = (),
        executor_class: type[ShoppingToolExecutor] = ShoppingToolExecutor,
    ) -> None:
        if skills is None:
            skills = SkillRegistry.from_dir(skills_dir) if skills_dir else SkillRegistry([])
        self.config = config or ShoppingAgentConfig()
        self.executor_class = executor_class
        self.backend = backend
        self.skills = skills
        self.client = client or AsyncAnthropic(timeout=self.config.request_timeout_s)
        self.extra_presentation_tools = tuple(extra_presentation_tools)
        self._specs: dict[str, PresentationComponent] = {
            **PRESENTATION_COMPONENTS,
            **{ext.name: ext for ext in self.extra_presentation_tools},
        }
        self._partial_ui_tools = partial_ui_tool_names(
            PRESENTATION_COMPONENTS, self.extra_presentation_tools
        )
        # 构建一次：每次请求的字节完全一样。流式渲染的展示工具要求 API
        # 在生成过程中就输出它们的参数。
        self._static_system = build_static_system(self.config, self.skills)
        self._tools = with_tool_cache_control(
            with_eager_input(
                build_tools(self.config, self.skills.names),
                self._partial_ui_tools,
            )
        )

    async def stream_turn(
        self,
        messages: list[dict[str, Any]],
        session: ShoppingSessionContext,
        state: ShoppingSessionState | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """跑一个轮次。``messages`` 以用户消息结尾，轮次过程中原地追加
        助手消息和工具结果，调用方直接存储即可；``state`` 携带会话的溯源记录，
        每个轮次传入并回传。"""
        state = state if state is not None else ShoppingSessionState()
        turn_started = time.monotonic()
        preferences, cart = await self._prefetch(session)
        # 第二个系统块，每个轮次构建一次：同一轮次内的各轮迭代和
        # 状态未变的各轮次之间字节相同（prompt_assembly）。
        context = build_dynamic_context(
            preferences=preferences,
            cart=cart,
        )
        system = build_system_blocks(self._static_system, context)
        executor = self.executor_class(
            backend=self.backend,
            config=self.config,
            skills=self.skills,
            session=session,
            state=state,
        )
        forced_tool = first_forced_tool(
            GROUNDING_RULES, self.config, latest_user_text(messages), state
        )
        usage = usage_totals()
        stop_reason: str | None = None
        last_prompt = 0

        # 调用方在 yield 处放弃轮次、或某轮迭代抛异常时，不能让存储的对话
        # 停在一个没有 tool_result 的 tool_use 上：下一次请求会被拒绝。
        # finally 给每个未配对的调用补上结果或错误。
        settled: dict[str, ToolOutcome] = {}
        try:
            for round_index in range(self.config.max_tool_iterations + 1):
                force_text = round_index == self.config.max_tool_iterations
                if force_text:
                    tool_choice: dict[str, str] = {"type": "none"}
                elif round_index == 0 and forced_tool:
                    tool_choice = {"type": "tool", "name": forced_tool}
                else:
                    tool_choice = {"type": "auto"}

                # 非 auto 轮次不打标记：tool_choice 是缓存消息段的键，
                # 在强制轮次下写入的条目对后续 auto 轮次不可读。
                request_messages = build_request_messages(
                    messages,
                    rolling_breakpoint=(
                        self.config.rolling_conversation_cache and tool_choice["type"] == "auto"
                    ),
                )
                request: dict[str, Any] = {
                    "model": self.config.model,
                    "max_tokens": self.config.max_tokens,
                    "system": system,
                    "tools": self._tools,
                    "tool_choice": tool_choice,
                    "messages": request_messages,
                    **self.config.thinking_request_fields(),
                }
                dispatcher = EagerDispatcher(
                    executor.execute, self.config.eager_tool_dispatch and not force_text
                )
                streamed = StreamedRound(
                    specs=self._specs,
                    partial_tools=self._partial_ui_tools,
                    state=state,
                    eager_frames=self.config.eager_partial_frames,
                )
                call_started = time.monotonic()
                # 这个 finally 是 dispatcher 的唯一兜底：已启动的执行
                # 不能比它的轮次活得更久；会导致泄漏的出口——流错误、
                # 格式异常、调用方在 yield 处关闭 generator——都经过这里。
                # collect 加入所有任务后，cancel 是空操作，正常路径零开销。
                try:
                    async with self.client.messages.stream(**cast(Any, request)) as stream:
                        async for event in streamed.relay(
                            stream, dispatcher, executor.tool_call_event
                        ):
                            yield event
                        final = None if streamed.abandoned else await stream.get_final_message()
                    response = final or streamed
                    log_model_call(
                        logger,
                        request,
                        response,
                        call_started,
                        session.session_id,
                        round=round_index,
                    )
                    if final is None:
                        # SDK 拒绝了一个流式卡片的非 JSON 输入。这轮迭代
                        # 保留到目前为止的内容，该调用以错误结果回答，
                        # 让模型重新发送；输入本身不记日志。
                        reply, tool_uses, unreadable = salvage_round(
                            streamed, dispatcher, logger, session.session_id, round_index
                        )
                    else:
                        reply = assistant_message(final)
                        tool_uses = [block for block in final.content if block.type == "tool_use"]
                        unreadable = set()
                    stop_reason = final.stop_reason if final else "tool_use"
                    accumulate_usage(usage, response)
                    last_prompt = prompt_tokens(response)
                    if reply is not None:
                        messages.append(reply)
                    if not tool_uses or force_text:
                        break

                    # 即时分派没有宣布的调用：启动晚了、或者根本没启动。
                    for block in tool_uses:
                        if block.id in unreadable or not dispatcher.started(block.id):
                            yield executor.tool_call_event(
                                block.name, block.id, dict(block.input or {})
                            )
                    outcomes = await dispatcher.collect(tool_uses)
                finally:
                    dispatcher.cancel()
                calls = list(zip(tool_uses, outcomes, strict=True))
                settled = {block.id: outcome for block, outcome in calls}
                for block, outcome in calls:
                    for event in outcome_events(block.name, block.id, outcome):
                        yield event
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            tool_result_block(block.id, outcome) for block, outcome in calls
                        ],
                    }
                )
                settled = {}
                if self.config.close_on_presentation and round_closes_turn(
                    ((block.name, outcome) for block, outcome in calls), executor.ends_clean
                ):
                    stop_reason = "end_turn"
                    break
        finally:
            close_open_tool_uses(messages, settled)

        cleared = compact_history(
            messages, last_prompt, self.config.compact_history_above_tokens, session.session_id
        )
        yield AgentEvent.turn_complete(stop_reason, usage, elapsed_ms(turn_started), cleared)

    async def _prefetch(
        self, session: ShoppingSessionContext
    ) -> tuple[UserPreferences | None, Cart | None]:
        # Step 16 加入 memory.tier_one 和 account 预取
        preferences, cart = await asyncio.gather(
            fetched(self.backend.get_preferences(session)),
            fetched(self.backend.get_cart(session) if self.config.enable_cart else None),
        )
        return preferences, cart
