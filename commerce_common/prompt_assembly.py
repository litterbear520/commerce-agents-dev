"""缓存断点的放置与每次请求的上下文组装。

角色模块决定两块**写什么**，本模块决定断点**放在哪**——所有路径共用。
"""
# 项目中对应 commerce-common/commerce_common/prompt_assembly.py

from __future__ import annotations

from collections.abc import Collection
from datetime import datetime
from typing import Any


def context_clock(now: datetime) -> str:
    """把当前时间截断到整点，保留时区。

    提示词和技能靠它拿日期和时段；要是精确到分钟，
    上下文块每分钟字节就不一样，几乎每轮对话都得重新写入缓存。
    """
    return now.replace(minute=0, second=0, microsecond=0).isoformat(timespec="minutes")


def build_system_blocks(static_text: str, context: str) -> list[dict[str, Any]]:
    """拼成两个系统块：静态文本带缓存断点，动态上下文跟在后面。

    第一个块里不放任何跟请求相关的东西；
    哪怕改了一个字节，工具列表和静态文本的缓存就全得重读。
    """
    return [
        {"type": "text", "text": static_text, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": context},
    ]


def with_eager_input(tools: list[dict[str, Any]], names: Collection[str]) -> list[dict[str, Any]]:
    """让 API 在生成过程中就流式输出这些工具的输入，而不是等顶层 value 完整后再发，
    这样一张卡片的第一个字段到达时就能开始渲染。输入按原样到达，不一定是合法 JSON；
    轮次循环把解析失败的调用作为错误回答（``StreamedRound``）。
    修改的是请求副本；registry 里的原始定义不变。"""
    return [t | {"eager_input_streaming": True} if t.get("name") in names else t for t in tools]


def with_tool_cache_control(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # 在最后一个工具上打缓存断点（第二个检查点）；返回浅拷贝，不动 registry 里的原始定义
    if not tools:
        return tools
    tools = [dict(t) for t in tools]
    tools[-1]["cache_control"] = {"type": "ephemeral"}
    return tools


def build_request_messages(
    messages: list[dict[str, Any]],
    *,
    rolling_breakpoint: bool = True,
) -> list[dict[str, Any]]:
    """给发出去的消息列表打滚动缓存断点，放在最新一条消息的最后一个 block 上。

    同一轮对话里系统块不变，所以这个断点让前几轮的消息（尤其是长工具结果）
    走缓存读取而不是重新处理。两种情况不打：只有一条消息时（一次性会话，
    写了也没人读），以及调用方传了 ``rolling_breakpoint=False`` 时
    （强制工具选择的轮次，缓存条目和后续 auto 轮次的键不同，读不到）。

    一轮对话在展示轮次上结束时，会留下一条 tool_result 消息紧接着下一条用户消息；
    这两条合成一条 user 消息发出去，tool_result 块在前。

    每次调用只作用于发出去的请求：返回的列表浅拷贝被改动的消息和块，去掉之前调用打的标记，
    绝不改调用方持久化的历史。字符串内容升格为单块列表，因为 ``cache_control`` 挂在内容块上。
    """
    if not messages:
        return []

    # 清除上一次调用打的断点标记
    def without_marker(message: dict[str, Any]) -> dict[str, Any]:
        content = message.get("content")
        if not isinstance(content, list) or not any(
            isinstance(b, dict) and "cache_control" in b for b in content
        ):
            return message
        return message | {
            "content": [
                {k: v for k, v in b.items() if k != "cache_control"} if isinstance(b, dict) else b
                for b in content
            ]
        }

    # 字符串内容升格为 block 列表，因为 cache_control 挂在 block 上
    def blocks(raw: Any) -> list[Any]:
        return [{"type": "text", "text": raw}] if isinstance(raw, str) else list(raw or [])

    # 遍历消息：清除旧标记，合并连续 user 消息
    request: list[dict[str, Any]] = []
    for message in messages:
        message = without_marker(message)
        if request and message.get("role") == "user" and request[-1].get("role") == "user":
            request[-1] = request[-1] | {
                "content": blocks(request[-1].get("content")) + blocks(message.get("content"))
            }
        else:
            request.append(message)

    # 在最新一条消息的最后一个 block 上打断点
    if not rolling_breakpoint or len(request) < 2:
        return request
    content = blocks(request[-1].get("content"))
    if content and isinstance(content[-1], dict):
        content[-1] = {**content[-1], "cache_control": {"type": "ephemeral"}}
        request[-1] = request[-1] | {"content": content}
    return request
