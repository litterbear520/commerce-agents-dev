"""清洗模型读到的文本数据。所有模式在恶意输入上都是线性时间。"""
# 项目中对应 commerce-common/commerce_common/fencing.py
# Fence 类还在 shopping_agent/fencing.py，Step 17 迁过来；
# 这里先重导出，让 memory.py 的 from .fencing import Fence 能工作。

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from shopping_agent.fencing import Fence as Fence  # noqa: F401 — Step 17 迁移后删除

# ── 清洗用的正则 ─────────────────────────────────────────────────────
# 跟 shopping_agent/fencing.py 里的定义一致，Step 17 合并时去重

# 零宽、双向文本和格式控制符：隐藏指令最常用的载体。
_INVISIBLE_RANGES = (
    (0x00AD, 0x00AD),  # 软连字符
    (0x200B, 0x200F),  # 零宽空格/连接符、LRM/RLM
    (0x2028, 0x2029),  # 行分隔符、段落分隔符
    (0x202A, 0x202E),  # 双向嵌入/覆盖
    (0x2060, 0x2064),  # 词连接符、不可见运算符
    (0x2066, 0x2069),  # 双向隔离
    (0x061C, 0x061C),  # 阿拉伯字母标记
    (0x180E, 0x180E),  # 蒙古文元音分隔符
    (0x206A, 0x206F),  # 已废弃的格式控制符
    (0xFE00, 0xFE0F),  # 变体选择符
    (0xFFF9, 0xFFFB),  # 行间注释控制符
    (0xFEFF, 0xFEFF),  # 字节序标记 / 零宽不换行空格
    (0xE0000, 0xE007F),  # 标签字符，能拼出不可见的 ASCII
    (0xE0100, 0xE01EF),  # 变体选择符补充
)
_INVISIBLE = re.compile("[" + "".join(f"{chr(lo)}-{chr(hi)}" for lo, hi in _INVISIBLE_RANGES) + "]")

# C0/C1 控制字符，tab 和换行除外。
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")

_WHITESPACE_RUN = re.compile(r"\s+")


# ── 标签清洗 ─────────────────────────────────────────────────────────

# 标签长度在 payload 验证时限制，而不是写进工具 schema——schema 是冻结的。
SUGGESTION_CHIP_MAX_CHARS = 80


def sanitize_label(text: Any, max_chars: int) -> str:
    """模型输出的单行文本（建议按钮、状态行）：去掉不可见字符和控制符，
    折叠空白，超过 ``max_chars`` 用省略号截断；什么都不剩时返回空串。"""
    line = _INVISIBLE.sub("", str(text or ""))
    line = _CONTROL.sub(" ", line)
    line = _WHITESPACE_RUN.sub(" ", line).strip()
    if len(line) > max_chars:
        line = line[: max_chars - 1].rstrip() + "…"
    return line


def sanitize_suggestion_chips(
    chips: Sequence[str],
    max_chips: int = 4,
    max_chars: int = SUGGESTION_CHIP_MAX_CHARS,
) -> list[str]:
    """把建议按钮列表清洗成单行标签：逐条过 ``sanitize_label``，
    丢掉空的，最多保留 ``max_chips`` 条。"""
    cleaned: list[str] = []
    for chip in chips:
        if label := sanitize_label(chip, max_chars):
            cleaned.append(label)
        if len(cleaned) == max_chips:
            break
    return cleaned
