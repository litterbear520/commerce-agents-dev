"""两个 agent 角色共用的数据类型。角色特有的类型放在各自的包里。"""
# 项目中对应 commerce-common/commerce_common/types.py
# 当前只有记忆相关的类型；PROVENANCE_CAP / remember / ClockContext 后续再加

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


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
