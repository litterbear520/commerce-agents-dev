"""商户门控，以及门控拦下时各条路径返回的措辞。暂存写入只接受本会话工具返回过的商品条目
id 和营销活动 id；对带选项的商品条目改价或补货，会被引导到它的变体上；应用和丢弃只接受
暂存或 ``get_pending_changes`` 返回过的变更 id；应用时重新检查护栏，部署要求审批时还要
检查调用方的审批标记。门控拦下时返回一个写明自己名字的 :class:`ToolOutcome`。
"""
# 项目中对应 merchant-agent/core/merchant_agent/gates.py
# 省略：STAGING_FOLLOWTHROUGH_REMINDER、turn_attempted_staging（Step 20 第 7 组）

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from commerce_common.streaming import ToolOutcome

from .changes import check_guardrails
from .config import MerchantAgentConfig
from .fencing import MERCHANT_FENCE
from .types import ActorKind, MerchantSessionState, PromotionDraft

PROVENANCE_GATE = "provenance"
OPTIONS_GATE = "options"
GUARDRAIL_GATE = "guardrail"
APPROVAL_GATE = "approval"

# 附在每个成功的 stage_* 结果上。
STAGED_NOTE = "只是暂存——用 present_change_preview 展示它，经营者审批这条变更之后才能应用。"
# 暂存调用自己展示了预览卡时（stage_shows_preview）换成这一句。
STAGED_AND_SHOWN_NOTE = (
    "已暂存，并已在预览卡上展示给经营者；这一轮不要再展示一次。经营者审批这条变更之后才能应用。"
)


def guardrail_block_message(violations: list[str]) -> str:
    return (
        "这条变更超出了本店的护栏："
        + "；".join(violations)
        + "。向经营者说明被拦下的原因，并提出一个合规的替代方案。"
    )


def apply_guardrail_message(violations: list[str]) -> str:
    return "按本店的护栏，这条变更已经不能应用：" + "；".join(violations)


def applied_confirmation(change_id: str, kind_value: str, operator: str) -> str:
    return (
        f"已以 {operator} 的身份应用 {change_id}（{kind_value}）。"
        "向经营者确认改了什么、现在在哪里能看到。"
    )


def coerce_object_arg(value: Any) -> dict[str, Any] | None:
    """返回这个 dict；模型把它当成 JSON 文本发来时也能解析出来；否则返回 None。"""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return None
        if isinstance(parsed, dict):
            return parsed
    return None


def coerce_array_arg(value: Any) -> list[Any] | None:
    """返回这个 list；模型把它当成 JSON 文本发来时也能解析出来；否则返回 None。"""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return None
        if isinstance(parsed, list):
            return parsed
    return None


def check_listing_provenance(
    state: MerchantSessionState, listing_ids: list[str]
) -> ToolOutcome | None:
    unknown = [lid for lid in listing_ids if lid not in state.seen_listings]
    if not unknown:
        return None
    return ToolOutcome.held(
        PROVENANCE_GATE,
        f"商品条目 id {'、'.join(unknown)} 不是本次会话中商品目录工具返回的。"
        "请先搜索或查询这些商品条目，再用结果里的 id。",
    )


def check_listing_options(
    state: MerchantSessionState, listing_ids: Iterable[str], verb: str
) -> ToolOutcome | None:
    """带选项的商品条目，价格和库存都在变体上，所以指定 family id 的写入会被拦下，
    并引导到变体 id。"""
    families = [
        lid for lid in listing_ids if (seen := state.seen_listings.get(lid)) and seen.has_options
    ]
    if not families:
        return None
    # 选项名是围栏外到达的商品目录文本：清洗并保持简短。
    names = MERCHANT_FENCE.sanitize_text(
        "、".join(dict.fromkeys(o for lid in families for o in state.seen_listings[lid].options)),
        max_chars=60,
    )
    return ToolOutcome.held(
        OPTIONS_GATE,
        f"商品条目 id {'、'.join(families)} 带有选项（{names}），{verb}要按变体分别进行。"
        "get_listing 会返回变体 id，get_pricing_context 给出每个变体的价格。经营者没有指定"
        "变体时，问一次是哪个；只有经营者说这次修改适用于全部变体，才按每个变体一个条目来暂存。",
    )


def check_listing_record_read(state: MerchantSessionState, listing_id: str) -> ToolOutcome | None:
    """内容编辑是对着完整记录暂存的，所以要先用 get_listing 读过。"""
    if listing_id in state.read_listings:
        return None
    return ToolOutcome.held(
        PROVENANCE_GATE,
        f"暂存商品条目的内容编辑需要完整记录：请先对 {listing_id} 调用 get_listing——"
        "搜索结果只是摘要，编辑要对着这个商品条目实际写的内容来改。",
    )


def check_campaign_provenance(
    state: MerchantSessionState, campaign_id: str | None
) -> ToolOutcome | None:
    """新建营销活动（没有 id）不受这道门控。"""
    if not campaign_id or campaign_id in state.seen_campaigns:
        return None
    return ToolOutcome.held(
        PROVENANCE_GATE,
        f"campaign_id {campaign_id} 不是本次会话中 get_campaign_performance 返回的。"
        "请先调用 get_campaign_performance，用结果里的活动 id；或者不带 campaign_id，"
        "暂存一个新营销活动。",
    )


def check_promotion_depth(
    promotion: PromotionDraft, config: MerchantAgentConfig
) -> ToolOutcome | None:
    """促销的折扣深度上限，在后端给促销定价之前检查。"""
    depth = abs(promotion.discount_pct)
    if depth <= config.max_promotion_discount_pct:
        return None
    return ToolOutcome.held(
        GUARDRAIL_GATE,
        f"{depth:.0f}% 的调价超过了本店 {config.max_promotion_discount_pct:.0f}% 的促销上限。"
        "请提出一个幅度更小的方案。",
    )


def check_apply_change(
    state: MerchantSessionState, config: MerchantAgentConfig, change_id: str
) -> ToolOutcome | None:
    """依次检查来源、按当前配置重新检查护栏、部署要求审批时检查调用方的审批标记。"""
    known = state.seen_changes.get(change_id)
    if known is None:
        return ToolOutcome.held(
            PROVENANCE_GATE,
            f"change_id {change_id} 不是本次会话暂存或列出过的。请先暂存这条变更"
            "（或调用 get_pending_changes），展示预览，经营者审批后再应用。",
        )
    if violations := check_guardrails(known.kind, known.items, config):
        return ToolOutcome.held(GUARDRAIL_GATE, apply_guardrail_message(violations))
    if config.require_host_approval and change_id not in state.approved_change_ids:
        return ToolOutcome.held(
            APPROVAL_GATE,
            f"变更 {change_id} 还没有在{config.approval_surface}上审批通过。告诉经营者它已经"
            f"暂存，正在{config.approval_surface}上等经营者审批——在那里审批通过就会应用它。",
        )
    return None


def check_discard_change(state: MerchantSessionState, change_id: str) -> ToolOutcome | None:
    if change_id in state.seen_changes:
        return None
    return ToolOutcome.held(
        PROVENANCE_GATE,
        f"change_id {change_id} 不是本次会话暂存或列出过的，没有可丢弃的内容。",
    )


def take_discard_actor_kind(state: MerchantSessionState, change_id: str) -> ActorKind:
    """调用方把这次丢弃标记为经营者本人的操作时，返回经营者（标记在这里用掉）；否则
    返回代表经营者行事的助手。"""
    if change_id in state.host_action_change_ids:
        state.host_action_change_ids.discard(change_id)
        return ActorKind.OPERATOR
    return ActorKind.AGENT
