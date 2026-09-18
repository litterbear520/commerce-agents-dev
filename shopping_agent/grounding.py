"""购物 agent 的数据锚定规则，按优先级排列：政策问题从 search_policies 开始，
售后问题从 get_orders 开始，消息中出现未见过的商品 ID 从 get_product_details 开始。
配置关掉的子系统对应的规则不触发。"""
# 项目中对应 shopping-agent/core/shopping_agent/grounding.py

from __future__ import annotations

from typing import Any

from commerce_common.grounding import GroundingRule, find_token, matches_terms_and_cues

from .config import ShoppingAgentConfig
from .types import ShoppingSessionState


def _policy(
    config: ShoppingAgentConfig, text: str, _: ShoppingSessionState
) -> dict[str, Any] | None:
    fires = (
        config.enable_policies
        and config.policy_grounding_gate
        and matches_terms_and_cues(text, config.policy_intent_terms, config.policy_intent_cues)
    )
    return {} if fires else None


def _orders(
    config: ShoppingAgentConfig, text: str, _: ShoppingSessionState
) -> dict[str, Any] | None:
    fires = (
        config.enable_orders
        and config.order_grounding_gate
        and matches_terms_and_cues(text, config.order_intent_terms, config.order_intent_cues)
    )
    return {} if fires else None


def _catalog(
    config: ShoppingAgentConfig, text: str, state: ShoppingSessionState
) -> dict[str, Any] | None:
    if not config.catalog_grounding_gate:
        return None
    token = find_token(text, config.product_id_patterns)
    # 会话已经解析过的 ID 不需要再强制读取；ID 比较不区分大小写。
    if token is None or token.upper() in {pid.upper() for pid in state.seen_products}:
        return None
    return {"product_id": token}


GROUNDING_RULES: tuple[GroundingRule, ...] = (
    GroundingRule("policy", "search_policies", _policy),
    GroundingRule(
        "orders",
        "get_orders",
        _orders,
        prefetch_intro=lambda _: (
            "Recent orders for this turn, fetched by the host (the same data a get_orders "
            "call returns):"
        ),
    ),
    GroundingRule(
        "catalog",
        "get_product_details",
        _catalog,
        prefetch_intro=lambda args: (
            f"Catalog record for {args['product_id']}, fetched by the host (the same data a "
            "get_product_details call returns):"
        ),
    ),
)
