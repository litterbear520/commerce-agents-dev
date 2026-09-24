"""两个角色共用的配置字段，各角色的配置按这里的分节顺序接着往下写：身份、模型、预算、
能力、记忆、上限。标了（提示词）的字段会渲染进静态提示词或工具列表，所以在一个部署内
保持不变；其余字段只影响运行时，从不改变提示词的字节。
"""
# 项目中对应 commerce-common/commerce_common/config.py
# 省略：enable_web_search（网页搜索，后续步骤用到时再加）

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .fencing import MAX_FENCED_CHARS

# 源码默认 claude-haiku-4-5-20251001；dev 环境用 DeepSeek 统一模型
DEFAULT_MEMORY_MODEL = "deepseek-v4-flash"

ThinkingEffort = Literal["low", "medium", "high", "xhigh", "max"]


class BaseAgentConfig(BaseModel):
    # 拼错的或已废弃的字段名在构造时就报错，而不是被悄悄忽略。
    model_config = ConfigDict(extra="forbid")

    # ── 身份（提示词） ──────────────────────────────────────────────
    brand_name: str = "本店"
    assistant_name: str = "助手"
    brand_voice: str = "直白具体"

    # ── 模型：对话循环跑在 `model` 上，由各角色的配置指定；对话结束后的记忆提取跑在
    # `memory_model` 上。对话循环按 `thinking_effort` 发送自适应思考，为 None 时关闭
    # 思考；无论哪种，`max_tokens` 都同时限制思考和回复的总长度。
    model: str
    memory_model: str = DEFAULT_MEMORY_MODEL
    thinking_effort: ThinkingEffort | None = None

    # ── 预算。迭代上限是防失控的保护：一个多步请求要远在上限之内完成，因为一旦上限
    # 强制进入一次不带工具的模型调用，模型往往会描述它根本没执行过的步骤。
    max_tokens: int = 2048
    max_tool_iterations: int = 8
    request_timeout_s: float = 120.0

    # ── 延迟。提前分派：工具调用的内容块一闭合就开始执行，此时模型还在写这次调用的
    # 其余部分；滚动缓存：把之前几次模型调用的消息和工具结果变成缓存读取；提前的局部帧：
    # payload 每次有可见变化都发一个 ``ui_partial`` 帧，而不只在结构变化时发；展示后
    # 收尾：一次模型调用里只有干净的展示型调用、并且包含 present_suggestions 时，直接
    # 结束对话轮次，不再请模型写一句收尾（Agent SDK 运行时用钩子结束；托管路径保留它
    # 自己的循环）。每个开关都能单独关掉，所以延迟问题可以逐个排查。
    eager_tool_dispatch: bool = True
    rolling_conversation_cache: bool = True
    eager_partial_frames: bool = False
    close_on_presentation: bool = True

    # ── 能力。记忆工具始终注册，`enable_memory` 在所有路径上切换它们的行为。
    enable_memory: bool = True

    # ── 记忆：每次请求注入的事实数（所有 constraint，然后是最近的），在默认标识符
    # 过滤之上的额外写入过滤正则（flag 内联），以及事实过期的天数，过期后既不注入也
    # 不召回（None 表示永久保留）。
    memory_tier_one_cap: int = Field(default=8, ge=0)
    memory_blocked_patterns: tuple[str, ...] = ()
    memory_retention_days: int | None = Field(default=None, ge=1)

    # ── 上限：后端每次请求的上下文 payload（超出时换成一句说明）、每次调用的搜索结果
    # 条数（模型给的 limit 会被限制在它以内）、每个围栏工具结果的字符数，以及提示词达到
    # 多大时，对话轮次结束时从存储的对话里清掉最早的工具结果（0 表示从不清）。默认值取
    # 平台自己的工具结果清理默认值，即模型窗口的十分之一：远在窗口成为瓶颈之前，成本和
    # 延迟就随每次模型调用增长了。
    max_context_chars: int = Field(default=2000, ge=0)
    max_search_results: int = Field(default=8, ge=1, le=25)
    max_fenced_chars: int = MAX_FENCED_CHARS
    compact_history_above_tokens: int = Field(default=100_000, ge=0)

    def absent_tools(self) -> frozenset[str]:
        """部署关掉的系统，角色的 `build_tools` 会去掉的工具名；执行器也拒绝它们。
        各角色的配置列出自己的。"""
        return frozenset()

    def thinking_request_fields(self) -> dict[str, Any]:
        """承载 `thinking_effort` 的请求字段，用于 agent 在 `model` 上发起的每次模型调用。"""
        if self.thinking_effort is None:
            return {"thinking": {"type": "disabled"}}
        return {
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": self.thinking_effort},
        }
