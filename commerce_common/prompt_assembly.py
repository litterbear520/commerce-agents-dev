"""缓存断点的放置与每次请求的上下文组装。

角色模块决定两块**写什么**，本模块决定断点**放在哪**——所有路径共用。
"""
# 项目中对应 commerce-common/commerce_common/prompt_assembly.py
# 当前只包含 context_clock，build_system_blocks / with_tool_cache_control /
# build_request_messages 在本 step 后续部分加入

from __future__ import annotations

from datetime import datetime


def context_clock(now: datetime) -> str:
    """上下文块里的会话时钟：当前小时，带会话的时区偏移。

    提示词和技能用它获取日期和时段；如果渲染分钟，
    上下文块每分钟就会变一次字节，导致几乎每轮对话都要重新读取。
    """
    return now.replace(minute=0, second=0, microsecond=0).isoformat(timespec="minutes")
