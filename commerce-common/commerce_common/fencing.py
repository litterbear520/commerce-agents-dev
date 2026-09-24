"""清洗、围栏模型当作数据读取的文本。每个角色定义一个 ``Fence``；它的标签名写死在源码里，
从不用运行时的值拼出来，所以不可信文本无法复刻这条边界。这里的每个模式在恶意输入上都是
线性时间：它们在截断之前就跑在事件循环上。
"""
# 项目中对应 commerce-common/commerce_common/fencing.py
# 省略：truncate_display（后续步骤用到时再加）

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache
from typing import Any

# ── 清洗用的正则 ─────────────────────────────────────────────────────

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

# 伪造的对话轮次边界：一个空行，然后是完整的角色词加冒号。句子中间的角色词、
# 单换行的标题、单字母的列表标记（"A:"）都不匹配。
_TURN_INDICATOR = re.compile(
    r"((?:\r\n|\r|\n)[ \t]*(?:\r\n|\r|\n)[ \t]*)(human|assistant|system|user)[ \t]*:",
    re.IGNORECASE,
)

# 围栏 body 开头的同一种标记：围栏自带的换行会把空行补全，而 body 内的模式看不到
# 这个换行，所以这条在包裹的时候才应用。
_LEADING_TURN_INDICATOR = re.compile(r"^(\s*)(human|assistant|system|user)[ \t]*:", re.IGNORECASE)

# 对话记录和工具调用的标记，可以带命名空间。只有标签形状的文本才匹配（裸标签、
# 闭合标签，或带 name="value" 属性的标签），所以 "<system requirements>" 能放行；
# parameter 和 result 只在带命名空间时才算。量词有上界且互不相邻，这正是它在
# 未闭合输入上保持线性的原因。
_TAG_ATTRS = (
    r"(?:[ \t]+[\w:.-]{1,40}[ \t]*=[ \t]*(?:\"[^\"]{0,200}\"|'[^']{0,200}'|[^\s\"'>]{1,200})){0,8}"
)
_SPECIAL_TOKEN = re.compile(
    r"<[ \t]*/?[ \t]*(?:"
    r"(?:[a-z][\w.-]{0,30}:)?(?:transcript|conversation|function_calls|function_results"
    r"|invoke|tool_use|tool_result|system|human|user|assistant)"
    r"|[a-z][\w.-]{0,30}:(?:parameter|result)"
    r")\b" + _TAG_ATTRS + r"[ \t]*/?>"
    r"|<\|[^|<>\r\n]{1,64}\|>",
    re.IGNORECASE,
)

_WHITESPACE_RUN = re.compile(r"\s+")

# 各角色配置里 ``max_fenced_chars`` 的默认值。
MAX_FENCED_CHARS = 12_000


# ── Fence ────────────────────────────────────────────────────────────


@cache
def _marker_pattern(label: str) -> re.Pattern[str]:
    # 标记指的是开尖括号后面的标签名，斜杠、空格、属性、闭合的尖括号都可有可无
    # （``</label x="">``、``< /label>``、``</label``）。
    return re.compile(rf"<\s*/?\s*{re.escape(label)}(?![A-Za-z0-9_])(?:[^<>]*>)?", re.IGNORECASE)


@dataclass(frozen=True)
class Fence:
    """包裹第三方内容的标签，以及静态提示词里关于它的信任说明。"""

    label: str
    notice: str

    @property
    def open(self) -> str:
        return f"<{self.label}>"

    @property
    def close(self) -> str:
        return f"</{self.label}>"

    def sanitize_text(self, text: str, max_chars: int | None = None) -> str:
        """``max_chars`` 限制结果长度（含截断后缀），可以直接传 schema 的字段上限。"""
        text = unicodedata.normalize("NFKC", text)
        text = _INVISIBLE.sub("", text)
        text = _CONTROL.sub(" ", text)
        # 标记和 token 反复移除直到不再变化，这样一个嵌在另一个里面的
        # （``</label</label>>``）在内层去掉后不会重新拼出来。
        marker = _marker_pattern(self.label)
        while True:
            stripped = _SPECIAL_TOKEN.sub("[removed]", marker.sub("[removed]", text))
            if stripped == text:
                break
            text = stripped
        text = _TURN_INDICATOR.sub(r"\1\2 -", text)
        if max_chars is not None and len(text) > max_chars:
            suffix = " ...[truncated]"
            if max_chars > len(suffix):
                text = text[: max_chars - len(suffix)] + suffix
            else:
                text = text[:max_chars]
        return text

    def sanitize_value(self, value: Any, max_chars: int | None = None) -> Any:
        if isinstance(value, str):
            return self.sanitize_text(value, max_chars)
        if isinstance(value, dict):
            return {
                self.sanitize_text(str(k), 200): self.sanitize_value(v, max_chars)
                for k, v in value.items()
            }
        if isinstance(value, (list, tuple)):
            # json.dumps 原生就能序列化元组，所以这里也要把元组遍历一遍。
            return [self.sanitize_value(v, max_chars) for v in value]
        return value

    def fence_payload(self, payload: Any, max_chars: int = MAX_FENCED_CHARS) -> str:
        """围栏里放清洗后的 payload。字符串叶子原地清洗；其他对象在转成字符串的时候清洗，
        这样 ``__str__`` 也夹带不进标记。"""
        sanitized = self.sanitize_value(payload)
        if isinstance(sanitized, str):
            body = sanitized
        else:
            body = json.dumps(
                sanitized, ensure_ascii=False, default=lambda v: self.sanitize_text(str(v))
            )
        if len(body) > max_chars:
            body = body[:max_chars] + " ...[truncated]"
        body = _LEADING_TURN_INDICATOR.sub(r"\1\2 -", body)
        return f"{self.open}\n{body}\n{self.close}"


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
