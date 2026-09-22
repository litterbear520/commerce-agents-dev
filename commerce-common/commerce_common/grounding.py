"""数据锚定规则：一条规则读用户消息，指定本轮必须从哪个只读工具开始，
让这类回答从工具结果出发。每个角色按优先级列出自己的规则；运行时强制
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

# 拉丁字母或数字：有它才谈得上词边界。汉字之间没有空格，``\b`` 在两个汉字
# 中间永远不成立，所以不含拉丁字母和数字的词条按子串匹配。
_WORD_BOUNDED = re.compile(r"[A-Za-z0-9]")


def matches_any(text: str, needles: Sequence[str]) -> bool:
    """大小写不敏感的整词（或整短语）匹配；``?`` 按字面匹配。
    不含拉丁字母和数字的词条（汉字、全角标点）按子串匹配。"""
    lowered = text.lower()
    for needle in needles:
        cleaned = needle.lower().strip()
        if not cleaned:
            continue
        if cleaned == "?" or not _WORD_BOUNDED.search(cleaned):
            if cleaned in lowered:
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
    """文本中任一模式的最长匹配（大小写不敏感），没有则返回 None。"""
    token: str | None = None
    for pattern in patterns if text else ():
        match = re.search(pattern, text, re.IGNORECASE)
        if match is not None and (token is None or len(match.group(0)) > len(token)):
            token = match.group(0)
    return token


FiresFn = Callable[[Any, str, Any], "dict[str, Any] | None"]


@dataclass(frozen=True)
class GroundingRule:
    """``fires(config, text, state)`` 在规则适用时返回 ``tool`` 的输入，否则返回 None。
    ``prefetch_intro`` 渲染预取时调用方放在工具结果上方的那行引导语；没有这一项的规则
    只在运行时能强制调用工具的地方才生效，因为它的输入要由模型来写。"""

    name: str
    tool: str
    fires: FiresFn
    prefetch_intro: Callable[[dict[str, Any]], str] | None = None


def first_forced_tool(
    rules: Sequence[GroundingRule], config: Any, text: str, state: Any
) -> str | None:
    """按规则优先级，返回本轮第一次迭代固定调用的工具。"""
    for rule in rules:
        if rule.fires(config, text, state) is not None:
            return rule.tool
    return None
