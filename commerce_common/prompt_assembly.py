"""缓存断点的放置与每次请求的上下文组装。

角色模块决定两块**写什么**，本模块决定断点**放在哪**——所有路径共用。
"""
# 项目中对应 commerce-common/commerce_common/prompt_assembly.py
# 当前只包含 context_clock，build_system_blocks / with_tool_cache_control /
# build_request_messages 在本 step 后续部分加入

from __future__ import annotations

from datetime import datetime


def context_clock(now: datetime) -> str:
    """把当前时间截断到整点，保留时区。

    提示词和技能靠它拿日期和时段；要是精确到分钟，
    上下文块每分钟字节就不一样，几乎每轮对话都得重新写入缓存。
    """
    return now.replace(minute=0, second=0, microsecond=0).isoformat(timespec="minutes")
