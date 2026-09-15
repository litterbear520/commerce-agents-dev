"""缓存断点的放置与每次请求的上下文组装。

角色模块决定两块**写什么**，本模块决定断点**放在哪**——所有路径共用。
"""
# 项目中对应 commerce-common/commerce_common/prompt_assembly.py
# 项目中 with_tool_cache_control / build_request_messages 在本 step 后续部分加入

from __future__ import annotations

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
