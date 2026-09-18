"""购物 agent 的工具执行器，每个工具一个 handler。Messages API、SDK 和 MCP
三条路径都通过这个类执行工具，因此同一个工具在每条路径上返回相同的结果。
"""
# 项目中对应 shopping-agent/core/shopping_agent/executor.py
# 项目中 ShoppingToolExecutor 继承 commerce_common 的 BaseToolExecutor，
# Step 17 再拆出基类；当前简化版把 execute/dispatch 直接写在这里

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from commerce_common.presentation import EnrichmentContext, run_presentation
from commerce_common.skills import SkillRegistry

from .backend import NotOffered, StorefrontBackend, Unavailable
from .config import ShoppingAgentConfig
from .enrichment import PRESENTATION_COMPONENTS
from .fencing import STOREFRONT_FENCE
from .gates import (
    gated_add_to_cart,
    gated_remove_from_cart,
    gated_update_cart_item,
    remember_order_items,
)
from .outcome import ToolOutcome
from .serialization import fulfillment_payload, order_payload, orders_payload, policies_payload
from .tools.registry import LOAD_SKILL
from .types import SearchFilters, ShoppingSessionContext, ShoppingSessionState

MAX_ORDERS = 20
MAX_FULFILLMENT_IDS = 20

logger = logging.getLogger(__name__)

# 类型别名：handler 是一个接收 tool_input 返回 ToolOutcome 的异步函数
Handler = Callable[[dict[str, Any]], Awaitable[ToolOutcome]]


class ShoppingToolExecutor:
    # 一个会话的工具执行器

    def __init__(
        self,
        *,
        backend: StorefrontBackend,
        config: ShoppingAgentConfig,
        session: ShoppingSessionContext,
        state: ShoppingSessionState,
        skills: SkillRegistry,
    ) -> None:
        self._backend = backend
        self._config = config
        self._session = session
        self._state = state
        self._skills = skills
        self._handlers: dict[str, Handler] = self.handlers()

    def handlers(self) -> dict[str, Handler]:
        return {
            "search_products": self._search_products,
            "get_product_details": self._get_product_details,
            "get_cart": self._get_cart,
            "add_to_cart": self._add_to_cart,
            "update_cart_item": self._update_cart_item,
            "remove_from_cart": self._remove_from_cart,
            "get_preferences": self._get_preferences,
            "get_orders": self._get_orders,
            "get_order_status": self._get_order_status,
            "search_policies": self._search_policies,
            "get_fulfillment_options": self._get_fulfillment_options,
        }

    # ── execute / dispatch ───────────────────────────────────────────

    async def execute(self, name: str, tool_input: dict[str, Any] | None) -> ToolOutcome:
        # 执行一次工具调用，永远不会抛异常
        # 分级异常处理：领域异常（Unavailable / NotOffered）→ 兜底 "暂时不可用"
        try:
            return await self.dispatch(name, dict(tool_input or {}))
        except Exception as error:
            if (outcome := self.domain_error(error)) is not None:
                return outcome
            logger.warning("tool %s failed", name, exc_info=True)
            return ToolOutcome.error(f"{name} 暂时不可用，请用已有的信息继续。")

    async def dispatch(self, name: str, tool_input: dict[str, Any]) -> ToolOutcome:
        """不带异常包裹的分派：异常会向上传播。"""
        if name == LOAD_SKILL:
            return self._load_skill(tool_input)
        if (spec := PRESENTATION_COMPONENTS.get(name)) is not None:
            return await self._present(spec, tool_input)
        handler = self._handlers.get(name)
        if handler is None:
            return ToolOutcome.error(f"未知工具：{name}")
        return await handler(tool_input)

    async def _present(self, spec, tool_input: dict[str, Any]) -> ToolOutcome:
        context = EnrichmentContext(
            backend=self._backend, config=self._config, session=self._session, state=self._state
        )
        return await run_presentation(spec, tool_input, context, "已展示给顾客。")

    def _load_skill(self, tool_input: dict[str, Any]) -> ToolOutcome:
        skill_name = str(tool_input.get("skill_name", ""))
        body = self._skills.get_instructions(skill_name)
        if body is None:
            return ToolOutcome.error(
                f"没有名为 '{skill_name}' 的技能。可用：{', '.join(self._skills.names)}"
            )
        return ToolOutcome(body)

    def domain_error(self, error: Exception) -> ToolOutcome | None:
        # 这段消息是围栏外到达的后端文本：清洗并限制长度。
        detail = STOREFRONT_FENCE.sanitize_text(str(error))[:200]
        if isinstance(error, Unavailable):
            return ToolOutcome.error(
                f"未加入购物车：{detail or '不可用'}。告知顾客，推荐消息中提到的有货替代品，"
                "只有顾客选择后才加入。"
            )
        if isinstance(error, NotOffered):
            return ToolOutcome.error(f"{detail or '该服务'}不是本店提供的，请直接告知顾客。")
        return None

    # ── 辅助方法 ─────────────────────────────────────────────────────

    def _fenced(self, payload: Any) -> ToolOutcome:
        return ToolOutcome(STOREFRONT_FENCE.fence_payload(payload))

    # ── handler：商品目录 ────────────────────────────────────────────

    async def _search_products(self, tool_input: dict[str, Any]) -> ToolOutcome:
        query = STOREFRONT_FENCE.sanitize_text(str(tool_input.get("query", "")))[:300]
        filters = SearchFilters(**tool_input["filters"]) if tool_input.get("filters") else None
        limit = min(int(tool_input.get("limit") or 8), 8)
        products = await self._backend.search_products(self._session, query, filters, limit)
        self._state.remember_products(products)
        return self._fenced([p.model_dump(exclude_none=True) for p in products])

    async def _get_product_details(self, tool_input: dict[str, Any]) -> ToolOutcome:
        product_id = str(tool_input.get("product_id", ""))
        details = await self._backend.get_product_details(self._session, product_id)
        if details is None:
            return ToolOutcome.error(f"没有 id 为 {product_id} 的商品。")
        # 变体随记录一起进入溯源，购物车才接受它们的 id。
        self._state.remember_products([details, *details.variants])
        return self._fenced(details.model_dump(exclude_none=True))

    # ── handler：购物车 ──────────────────────────────────────────────

    async def _get_cart(self, _: dict[str, Any]) -> ToolOutcome:
        cart = await self._backend.get_cart(self._session)
        return self._fenced(cart.model_dump(exclude_none=True))

    async def _add_to_cart(self, tool_input: dict[str, Any]) -> ToolOutcome:
        # 三个购物车写操作都经过 gates.py：溯源、选项、数量上限，同一会话串行
        return await gated_add_to_cart(
            backend=self._backend,
            config=self._config,
            session=self._session,
            state=self._state,
            product_id=str(tool_input.get("product_id", "")),
            quantity=int(tool_input.get("quantity") or 1),
        )

    async def _update_cart_item(self, tool_input: dict[str, Any]) -> ToolOutcome:
        return await gated_update_cart_item(
            backend=self._backend,
            config=self._config,
            session=self._session,
            state=self._state,
            product_id=str(tool_input.get("product_id", "")),
            quantity=int(tool_input.get("quantity") or 1),
        )

    async def _remove_from_cart(self, tool_input: dict[str, Any]) -> ToolOutcome:
        return await gated_remove_from_cart(
            backend=self._backend,
            session=self._session,
            state=self._state,
            product_id=str(tool_input.get("product_id", "")),
        )

    # ── handler：用户上下文、订单、政策、履约 ────────────────────────

    async def _get_preferences(self, _: dict[str, Any]) -> ToolOutcome:
        prefs = await self._backend.get_preferences(self._session)
        return self._fenced(prefs.model_dump(exclude_none=True))

    async def _get_orders(self, tool_input: dict[str, Any]) -> ToolOutcome:
        limit = max(1, min(int(tool_input.get("limit") or 5), MAX_ORDERS))
        orders = await self._backend.get_orders(self._session, limit)
        remember_order_items(self._state, orders)
        return self._fenced(orders_payload(orders))

    async def _get_order_status(self, tool_input: dict[str, Any]) -> ToolOutcome:
        order_id = str(tool_input.get("order_id", ""))
        order = await self._backend.get_order(self._session, order_id)
        if order is None:
            return ToolOutcome.error(f"没有 id 为 {order_id} 的订单。")
        remember_order_items(self._state, [order])
        return self._fenced(order_payload(order))

    async def _search_policies(self, tool_input: dict[str, Any]) -> ToolOutcome:
        query = STOREFRONT_FENCE.sanitize_text(str(tool_input.get("query", "")))[:200]
        policies = await self._backend.search_policies(self._session, query)
        return self._fenced(policies_payload(policies))

    async def _get_fulfillment_options(self, tool_input: dict[str, Any]) -> ToolOutcome:
        product_ids = [str(pid) for pid in tool_input.get("product_ids") or []][
            :MAX_FULFILLMENT_IDS
        ]
        options = await self._backend.get_fulfillment_options(self._session, product_ids)
        return self._fenced(fulfillment_payload(options))
