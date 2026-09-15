# 项目中对应 commerce_common/streaming.py 的 ToolOutcome
# Step 17 迁到 commerce_common 时再搬过去

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ToolOutcome:
    """一次工具调用的结果：``result_text`` 给模型看。
    ``blocked`` 记录哪个门控拦截了调用；``is_error`` 表示失败。"""

    result_text: str
    is_error: bool = False
    blocked: str | None = None

    @classmethod
    def error(cls, text: str) -> ToolOutcome:
        return cls(text, is_error=True)

    @classmethod
    def held(cls, gate: str, text: str) -> ToolOutcome:
        # held：操作被门控搁置，不是错误，模型可以按提示恢复
        return cls(text, blocked=gate)

    @property
    def refused(self) -> bool:
        # 被拒绝：错误或门控拦截
        return self.is_error or self.blocked is not None
