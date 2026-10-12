"""暂存变更的护栏，以及示例后端直接拿来用的内存版 ``ChangeLedger``。护栏在暂存时检查一次，
应用前再检查一次。
"""
# 项目中对应 merchant-agent/core/merchant_agent/changes.py

from __future__ import annotations

from datetime import UTC, datetime

from commerce_common.fencing import truncate_display

from .config import MerchantAgentConfig
from .types import ActorKind, ChangeItem, ChangeKind, ChangeStatus, StagedChange


class GuardrailViolation(ValueError):
    """变更违反了护栏；``violations`` 里每条规则一条消息。"""

    def __init__(self, violations: list[str]):
        super().__init__("；".join(violations))
        self.violations = violations


class ChangeNotApplicable(ValueError):
    """变更 id 不存在，或者它当前的状态不允许这次流转；后端遇到自己系统没有的操作时也抛它。
    执行器会把消息转给模型。"""


def check_guardrails(
    kind: ChangeKind, items: list[ChangeItem], config: MerchantAgentConfig
) -> list[str]:
    """返回这批条目违反的每条护栏，消息写给经营者看；列表为空表示可以继续。"""
    violations: list[str] = []
    if len(items) > config.max_items_per_change:
        violations.append(
            f"这次变更涉及 {len(items)} 个条目，上限是每次 {config.max_items_per_change} 个；"
            "请拆成几次不超过上限的变更，分别审批"
        )
    protected = {name.casefold() for name in config.protected_fields}
    listing_blocked = {name.casefold() for name in config.listing_update_blocked_fields}
    price_bearing = {name.casefold() for name in config.price_bearing_fields}
    seen: set[tuple[str, str]] = set()
    for item in items:
        field = item.field.casefold()
        # 下面的上限按条目逐个检查，预览卡也是一个条目一行；同一个目标在一次变更里重复出现，
        # 每次重复都能单独通过上限，应用时却会叠加。
        if (item.target, field) in seen:
            violations.append(
                f"{item.target} 的 '{item.field}' 在这次变更里出现了不止一次——每个条目只写一行"
            )
        seen.add((item.target, field))
        if field in protected:
            violations.append(f"{item.target} 的字段 '{item.field}' 受保护，助手不能修改")
        if kind is ChangeKind.LISTING_UPDATE and field in listing_blocked:
            violations.append(
                f"'{item.field}' 不能放在商品信息修改里改——请作为改价或库存操作暂存，"
                "这样才会套用它自己的上限"
            )
        # 促销的条目不管字段叫什么都是价格变动，按促销上限检查；其他价格变动按单次上限检查。
        if field in price_bearing or kind is ChangeKind.PROMOTION:
            before = _as_price(item.before)
            after = _as_price(item.after)
            if after is None:
                violations.append(f"{item.target} 的价格必须是正数")
            elif before is None:
                violations.append(f"{item.target} 没有可依据的当前价格——无法检查变动幅度上限")
            else:
                delta_pct = abs(after - before) / before * 100
                if kind is ChangeKind.PROMOTION:
                    if delta_pct > config.max_promotion_discount_pct:
                        violations.append(
                            f"{item.target} 的促销变动 {delta_pct:.0f}% 超过了 "
                            f"{config.max_promotion_discount_pct:.0f}% 的促销上限"
                        )
                elif delta_pct > config.max_price_delta_pct:
                    violations.append(
                        f"{item.target} 的价格变动 {delta_pct:.0f}% 超过了单次 "
                        f"{config.max_price_delta_pct:.0f}% 的上限"
                    )
        # 任何让库存水平上升的库存操作都算补货。
        if kind is ChangeKind.INVENTORY_ACTION:
            added = _as_quantity(item.after) - _as_quantity(item.before)
            if added > config.max_restock_quantity:
                violations.append(
                    f"{item.target} 补货 {added} 件，超过了单次 "
                    f"{config.max_restock_quantity} 件的上限"
                )
        if kind is ChangeKind.CAMPAIGN and field == "budget":
            budget = _as_price(item.after)
            if budget is not None and budget > config.max_campaign_budget:
                violations.append(
                    f"营销预算 {budget:.0f} 超过了单次 {config.max_campaign_budget:.0f} 的上限"
                )
    return violations


def _as_price(value: object) -> float | None:
    try:
        price = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return price if price > 0 else None


def _as_quantity(value: object) -> int:
    try:
        return int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return 0


class ChangeLedger:
    """内存版的暂存变更生命周期，MerchantBackend 可以直接拿来用。``stage`` 检查护栏并记录操作者；
    ``apply`` 和 ``discard`` 只接受当前处于暂存状态的变更；已应用和已丢弃的变更留在台账里，
    作为审计记录。"""

    def __init__(self, config: MerchantAgentConfig):
        self._config = config
        self._changes: dict[str, StagedChange] = {}
        self._sequence = 0

    def stage(
        self,
        *,
        kind: ChangeKind,
        summary: str,
        items: list[ChangeItem],
        actor: str,
        actor_kind: ActorKind = ActorKind.OPERATOR,
        currency: str | None = None,
        margin_impact: float | None = None,
        margin_before_pct: float | None = None,
        margin_after_pct: float | None = None,
        guardrail_notes: list[str] | None = None,
    ) -> StagedChange:
        violations = check_guardrails(kind, items, self._config)
        if violations:
            raise GuardrailViolation(violations)
        self._sequence += 1
        change = StagedChange(
            change_id=f"chg-{self._sequence:04d}",
            kind=kind,
            status=ChangeStatus.STAGED,
            # 摘要是预览卡上的展示文字，过长时截断而不是拒绝。
            summary=truncate_display(summary, 200),
            items=items,
            created_at=datetime.now(UTC),
            created_by=actor,
            created_by_kind=actor_kind,
            guardrail_notes=guardrail_notes or [],
            currency=currency,
            margin_impact=margin_impact,
            margin_before_pct=margin_before_pct,
            margin_after_pct=margin_after_pct,
        )
        self._changes[change.change_id] = change
        return change

    def get(self, change_id: str) -> StagedChange | None:
        return self._changes.get(change_id)

    def pending(self) -> list[StagedChange]:
        return [c for c in self._changes.values() if c.status is ChangeStatus.STAGED]

    def applied(self) -> list[StagedChange]:
        return [c for c in self._changes.values() if c.status is ChangeStatus.APPLIED]

    def resolved(self) -> list[StagedChange]:
        """已应用和已丢弃的变更，供后台的审计视图使用。"""
        return [c for c in self._changes.values() if c.status is not ChangeStatus.STAGED]

    def apply(self, change_id: str, actor: str) -> StagedChange:
        change = self._require_staged(change_id, "应用")
        # 暂存之后配置可能调严了。
        violations = check_guardrails(change.kind, change.items, self._config)
        if violations:
            raise GuardrailViolation(violations)
        updated = change.model_copy(
            update={
                "status": ChangeStatus.APPLIED,
                "applied_at": datetime.now(UTC),
                "applied_by": actor,
            }
        )
        self._changes[change_id] = updated
        return updated

    def discard(
        self, change_id: str, actor: str, actor_kind: ActorKind = ActorKind.OPERATOR
    ) -> StagedChange:
        change = self._require_staged(change_id, "丢弃")
        updated = change.model_copy(
            update={
                "status": ChangeStatus.DISCARDED,
                "discarded_at": datetime.now(UTC),
                "discarded_by": actor,
                "discarded_by_kind": actor_kind,
            }
        )
        self._changes[change_id] = updated
        return updated

    def _require_staged(self, change_id: str, action: str) -> StagedChange:
        change = self._changes.get(change_id)
        if change is None:
            raise ChangeNotApplicable(f"没有 id 为 {change_id!r} 的变更可以{action}")
        if change.status is not ChangeStatus.STAGED:
            raise ChangeNotApplicable(
                f"变更 {change_id} 的状态是 {change.status.value}，已不在暂存中——没有可{action}的内容"
            )
        return change
