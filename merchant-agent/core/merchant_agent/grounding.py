"""商户 agent 的数据锚定规则，按优先级排列：业绩问题从 get_business_snapshot 开始。"""
# 项目中对应 merchant-agent/core/merchant_agent/grounding.py
# 省略：审批队列规则 _queue 和跟进提醒的检测函数 change_requested（Step 20）

from __future__ import annotations

from typing import Any

from commerce_common.grounding import GroundingRule, matches_terms_and_cues

from .config import MerchantAgentConfig
from .types import MerchantSessionState


def _metrics(
    config: MerchantAgentConfig, text: str, _: MerchantSessionState
) -> dict[str, Any] | None:
    fires = config.metrics_grounding_gate and matches_terms_and_cues(
        text, config.metrics_intent_terms, config.metrics_intent_cues
    )
    return {} if fires else None


GROUNDING_RULES: tuple[GroundingRule, ...] = (
    GroundingRule(
        "metrics",
        "get_business_snapshot",
        _metrics,
        prefetch_intro=lambda _: (
            "本轮的经营快照，由调用方预取（与 get_business_snapshot 返回的数据相同）："
        ),
    ),
)
