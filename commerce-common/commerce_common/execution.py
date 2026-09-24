"""两个角色共同扩展的执行器框架。角色执行器提供自己的围栏、handler 表和措辞；本模块
负责分派、失败分级、技能、展示、委托、记忆，以及非展示调用可以带给等待者的 ``status``
行，所以每个工具结果都在同一个地方构建，Messages API 运行时、Agent SDK 工具集和 MCP
服务器都调用 ``execute``。
"""
# 项目中对应 commerce-common/commerce_common/execution.py
# 省略：status 行（STATUS_FIELD、with_status、split_status 等）、参数校验
# （InvalidArguments、parse_argument）、clamp_limit、_search_limit、展示扩展、
# 委托（Step 21）、进度事件；后续步骤用到时再加

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from .fencing import Fence
from .memory import MemoryRuntime
from .presentation import EnrichmentContext, PresentationComponent, run_presentation
from .skills import SkillRegistry
from .streaming import AgentEvent, ToolOutcome

logger = logging.getLogger(__name__)

LOAD_SKILL = "load_skill"

Handler = Callable[[dict[str, Any]], Awaitable[ToolOutcome]]


class BaseToolExecutor:
    """一个会话的工具。子类设置类属性，实现 :meth:`handlers` 和 :attr:`memory_subject`；
    ``execute`` 从不抛异常。"""

    fence: Fence
    components: Mapping[str, PresentationComponent]
    displayed_text: str
    unavailable_text: str  # 用 {name} 格式化
    # 配置关掉的工具：这里没有这个系统，不算故障。
    absent_text: str = "{name} 不是这里提供的功能；直接说明，不要推荐它。"

    def __init__(
        self,
        *,
        backend: Any,
        config: Any,
        skills: SkillRegistry,
        session: Any,
        state: Any,
        memory: MemoryRuntime,
    ) -> None:
        self._backend = backend
        self._config = config
        self._absent = config.absent_tools()
        self._skills = skills
        self._session = session
        self._state = state
        self._memory = memory
        self._handlers: dict[str, Handler] = {
            **self.handlers(),
            "save_memory": self._save_memory,
            "recall_memories": self._recall_memories,
        }

    # ── 角色钩子 ────────────────────────────────────────────────────

    def handlers(self) -> dict[str, Handler]:
        raise NotImplementedError

    @property
    def memory_subject(self) -> str:
        raise NotImplementedError

    def domain_error(self, error: Exception) -> ToolOutcome | None:
        """角色自己的异常类映射成的结果；返回 None 就走通用的失败分级。"""
        return None

    # ── 给 handler 用的辅助方法 ─────────────────────────────────────

    def _sanitize(self, value: Any, max_chars: int | None) -> str:
        return self.fence.sanitize_text(str(value or ""), max_chars)

    def _fenced(self, payload: Any, events: Sequence[AgentEvent] = ()) -> ToolOutcome:
        return ToolOutcome(
            self.fence.fence_payload(payload, self._config.max_fenced_chars), list(events)
        )

    # ── 分派 ────────────────────────────────────────────────────────

    def presents(self, name: str) -> bool:
        """``name`` 是展示型工具时为 True。"""
        return name in self.components

    def tool_call_event(
        self, name: str, tool_use_id: str, tool_input: dict[str, Any]
    ) -> AgentEvent:
        """发给调用方的 ``tool_call`` 事件。"""
        return AgentEvent.tool_call(name, tool_use_id, tool_input)

    def ends_clean(self, name: str, outcome: ToolOutcome) -> bool:
        """这次调用可以留在结束对话轮次的那次模型调用里、不再请模型收尾时为 True：
        一次渲染成功、没给模型留下任何要回应的东西的展示调用（没有被拒绝或拦截，
        结果里也没有追加备注）。"""
        return (
            self.presents(name)
            and not outcome.refused
            and outcome.result_text == self.displayed_text
        )

    async def execute(self, name: str, tool_input: dict[str, Any] | None) -> ToolOutcome:
        try:
            return await self.dispatch(name, dict(tool_input or {}))
        except Exception as error:  # 工具失败不能让对话轮次中断
            if (outcome := self.domain_error(error)) is not None:
                return outcome
            logger.warning("工具 %s 执行失败，按暂时不可用报告", name, exc_info=True)
            return ToolOutcome.error(self.unavailable_text.format(name=name))

    async def dispatch(self, name: str, tool_input: dict[str, Any]) -> ToolOutcome:
        """不带失败分级的 :meth:`execute`：工具抛出的异常会向上传播，所以预取读数据的
        调用方能分清是工具失败了，还是工具自己写了结果（没找到的说明、被拦截的调用）。
        部署配置从工具列表里去掉的工具，不论哪条路径调用，这里也当作未知。"""
        if name in self._absent:
            return ToolOutcome.error(self.absent_text.format(name=name))
        if name == LOAD_SKILL:
            return self._load_skill(tool_input)
        if (spec := self.components.get(name)) is not None:
            return await self._present(spec, tool_input)
        handler = self._handlers.get(name)
        if handler is None:
            return ToolOutcome.error(f"未知工具：{name}")
        return await handler(tool_input)

    def _load_skill(self, tool_input: dict[str, Any]) -> ToolOutcome:
        skill_name = str(tool_input.get("skill_name", ""))
        body = self._skills.get_instructions(skill_name)
        if body is None:
            return ToolOutcome.error(
                f"没有名为 '{skill_name}' 的技能。可用：{', '.join(self._skills.names)}"
            )
        return ToolOutcome(body)

    async def _present(
        self, spec: PresentationComponent, tool_input: dict[str, Any]
    ) -> ToolOutcome:
        context = EnrichmentContext(
            backend=self._backend, config=self._config, session=self._session, state=self._state
        )
        return await run_presentation(spec, tool_input, context, self.displayed_text)

    async def _save_memory(self, tool_input: dict[str, Any]) -> ToolOutcome:
        return await self._memory.save(self.memory_subject, self._session.session_id, tool_input)

    async def _recall_memories(self, tool_input: dict[str, Any]) -> ToolOutcome:
        return await self._memory.recall(self.memory_subject, tool_input)
