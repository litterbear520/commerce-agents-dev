"""缓存断点的放置与每次请求的上下文组装。

静态系统提示词带 ``cache_control: ephemeral``，动态上下文紧随其后单独一块；
工具列表的最后一个工具带第二个缓存断点；滚动断点放在最新一条已持久化的消息上。
角色模块决定两块**写什么**，本模块决定断点**放在哪**——所有路径共用。
"""
# 项目中对应 commerce-common/commerce_common/prompt_assembly.py
# 当前只包含 context_clock，build_system_blocks / with_tool_cache_control /
# build_request_messages 在本 step 后续部分加入

from __future__ import annotations

from datetime import datetime


def context_clock(now: datetime) -> str:
    """会话时钟：只渲染到小时，不渲染分钟。

    提示词和技能用它获取日期和时段；如果渲染分钟，
    动态上下文块每分钟就会变一次，每次变化都让消息历史的缓存失效。
    """
    return now.replace(minute=0, second=0, microsecond=0).isoformat(timespec="minutes")
