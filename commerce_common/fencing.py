"""清洗模型读到的文本数据。所有模式在恶意输入上都是线性时间。"""
# 项目中对应 commerce-common/commerce_common/fencing.py
# 当前只包含 sanitize_label / sanitize_suggestion_chips
# Fence 类、fence_payload 等到 Step 17 从 shopping_agent/fencing.py 迁过来

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

# ── 清洗用的正则 ─────────────────────────────────────────────────────
# 跟 shopping_agent/fencing.py 里的定义一致，Step 17 合并时去重

_INVISIBLE_RANGES = (
    (0x00AD, 0x00AD),
    (0x200B, 0x200F),
    (0x2028, 0x2029),
    (0x202A, 0x202E),
    (0x2060, 0x2064),
    (0x2066, 0x2069),
    (0x061C, 0x061C),
    (0x180E, 0x180E),
    (0x206A, 0x206F),
    (0xFE00, 0xFE0F),
    (0xFFF9, 0xFFFB),
    (0xFEFF, 0xFEFF),
    (0xE0000, 0xE007F),
    (0xE0100, 0xE01EF),
)
_INVISIBLE = re.compile("[" + "".join(f"{chr(lo)}-{chr(hi)}" for lo, hi in _INVISIBLE_RANGES) + "]")

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")

_WHITESPACE_RUN = re.compile(r"\s+")


# ── 标签清洗 ─────────────────────────────────────────────────────────

SUGGESTION_CHIP_MAX_CHARS = 80


def sanitize_label(text: Any, max_chars: int) -> str:
    """模型输出的单行文本（芯片、状态行）：去掉不可见字符和控制符，
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
    """把芯片列表清洗成单行按钮标签：逐条过 ``sanitize_label``，
    丢掉空的，最多保留 ``max_chips`` 条。"""
    cleaned: list[str] = []
    for chip in chips:
        if label := sanitize_label(chip, max_chars):
            cleaned.append(label)
        if len(cleaned) == max_chips:
            break
    return cleaned
