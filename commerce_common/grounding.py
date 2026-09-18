"""数据锚定规则：一条规则读用户消息，指定本轮必须从哪个只读工具开始，
让回答建立在工具结果之上。每个角色按优先级列出自己的规则；运行时强制
第一条触发的规则，没有 tool_choice 的调用方则预取它。词汇表是配置；
本模块只做匹配。"""
# 项目中对应 commerce-common/commerce_common/grounding.py

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

# 具体的金额或百分比数字本身就算一个意图词。
_MONEY_LITERAL = re.compile(r"\$\s?\d")
_PERCENT_LITERAL = re.compile(r"\d+\s?%")


def matches_any(text: str, needles: Sequence[str]) -> bool:
    """大小写不敏感的整词（或整短语）匹配；``?`` 按字面匹配。"""
    lowered = text.lower()
    for needle in needles:
        cleaned = needle.lower().strip()
        if not cleaned:
            continue
        if cleaned == "?":
            if "?" in lowered:
                return True
        elif re.search(rf"\b{re.escape(cleaned)}\b", lowered):
            return True
    return False


def matches_terms_and_cues(
    text: str, terms: Sequence[str], cues: Sequence[str], *, numeric_literals: bool = False
) -> bool:
    """文本同时包含一个意图词和一个线索词时返回 True。
    ``numeric_literals`` 开启时，金额或百分比也算意图词。
    空文本或空词汇表不触发。"""
    if not text or not terms or not cues or not matches_any(text, cues):
        return False
    if matches_any(text, terms):
        return True
    return numeric_literals and bool(_MONEY_LITERAL.search(text) or _PERCENT_LITERAL.search(text))


def find_token(text: str, patterns: Sequence[str]) -> str | None:
    """返回文本中最长的正则匹配（大小写不敏感），用于提取商品 ID；无匹配返回 None。"""
    token: str | None = None
    for pattern in patterns if text else ():
        match = re.search(pattern, text, re.IGNORECASE)
        if match is not None and (token is None or len(match.group(0)) > len(token)):
            token = match.group(0)
    return token


FiresFn = Callable[[Any, str, Any], "dict[str, Any] | None"]


@dataclass(frozen=True)
class GroundingRule:
    """``fires(config, text, state)`` 在规则适用时返回工具输入参数，否则返回 None。
    ``prefetch_intro`` 渲染预取调用方放在工具结果前面的引导行；没有它的规则
    只在运行时能强制工具时才生效，因为它的输入由模型来写。"""

    name: str
    tool: str
    fires: FiresFn
    prefetch_intro: Callable[[dict[str, Any]], str] | None = None


def first_forced_tool(
    rules: Sequence[GroundingRule], config: Any, text: str, state: Any
) -> str | None:
    """按规则优先级依次检查，返回本轮首轮应强制调用的工具名。"""
    for rule in rules:
        if rule.fires(config, text, state) is not None:
            return rule.tool
    return None
