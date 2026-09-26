"""两个 agent 角色共用的数据类型。角色特有的类型放在各自的包里。"""
# 项目中对应 commerce-common/commerce_common/types.py

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TypeVar
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator

# 溯源记录保留的条数：留最新的；被淘汰的 id 要重新读一次才能再用。
PROVENANCE_CAP = 200

RecordT = TypeVar("RecordT")


def remember(records: dict[str, RecordT], key: str, value: RecordT) -> None:
    records.pop(key, None)
    records[key] = value
    while len(records) > PROVENANCE_CAP:
        del records[next(iter(records))]


class MemoryCategory(StrEnum):
    PREFERENCE = "preference"
    CONSTRAINT = "constraint"
    CONTEXT = "context"


class MemoryFact(BaseModel):
    """一条存储的事实。schema 约束形状；``validate_fact`` 决定值可以涉及什么。
    constraint 类型的事实在每个轮次都会注入。"""

    key: str = Field(max_length=64)
    value: str = Field(max_length=200)
    category: MemoryCategory = MemoryCategory.PREFERENCE
    updated_at: datetime | None = None
    # 召回的事实带上写入它的会话标识，这样模型把它们当作过去轮次的声明，
    # 而被投毒的会话写入也可以溯源。值是 session_tag 而不是 id：
    # 事实会被同一用户的其他会话读回，而在示例调用方里 id 也是请求凭证。
    source_session_id: str | None = Field(default=None, max_length=80)


class ClockContext(BaseModel):
    """调用方提供给会话上下文的时钟：一个 IANA ``timezone``，或者一个覆盖它的显式
    ``now``。两者都没设时提示词里不带本地时间，因为服务器的时钟不是用户的时钟。"""

    timezone: str | None = None
    now: datetime | None = None

    @field_validator("timezone")
    @classmethod
    def _known_zone(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                ZoneInfo(value)
            except (KeyError, ValueError) as exc:
                raise ValueError(f"未知的 IANA 时区：{value!r}") from exc
        return value

    def local_now(self) -> datetime | None:
        if self.now is not None:
            return self.now
        if self.timezone is not None:
            return datetime.now(ZoneInfo(self.timezone))
        return None
