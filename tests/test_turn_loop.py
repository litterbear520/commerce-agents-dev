"""两个轮次循环都要遵守的约定：会话时钟。"""
# 项目中对应 tests/test_turn_loop.py
# 省略：缓存字节、滚动断点与上下文块、提前分派、强制文字回复、被拦截的结果、历史压缩、
# 轮次写入和上报的记录（两个编排器都到位后补，Step 19 起）

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from commerce_common.types import ClockContext


def test_clock_context_prefers_an_explicit_now_and_rejects_unknown_zones():
    assert ClockContext().local_now() is None
    assert ClockContext(timezone="Europe/Lisbon").local_now().tzinfo == ZoneInfo("Europe/Lisbon")
    fixed = datetime(2026, 5, 30, 10, 0, tzinfo=ZoneInfo("Europe/Lisbon"))
    assert ClockContext(timezone="America/New_York", now=fixed).local_now() is fixed
    with pytest.raises(ValidationError):
        ClockContext(timezone="Mars/Olympus_Mons")
