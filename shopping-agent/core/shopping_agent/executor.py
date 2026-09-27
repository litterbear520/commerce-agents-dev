"""购物 agent 的工具，建在共享执行器框架上，每个工具一个 handler。Messages API 运行时、
SDK 工具集和 MCP 服务器都通过这个类执行工具，所以同一个工具在每条路径上返回相同的字节。
"""
# 项目中对应 shopping-agent/core/shopping_agent/executor.py
# 省略：inline_context（SDK / MCP 路径用）、展示扩展

from __future__ import annotations

from typing import Any

from commerce_common.execution import BaseToolExecutor, Handler, parse_argument
from commerce_common.memory import MemoryRuntime
from commerce_common.skills import SkillRegistry
from commerce_common.streaming import ToolOutcome

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
from .memory import SHOPPING_MEMORY_EXTRACTION_PROMPT
from .serialization import (
    fulfillment_payload,
    order_payload,
    orders_payload,
    policies_payload,
    product_details_payload,
    search_result_text,
)
from .types import SearchFilters, ShoppingSessionContext, ShoppingSessionState

MAX_ORDERS = 20
MAX_FULFILLMENT_IDS = 20


def build_memory(
    config: ShoppingAgentConfig, store: Any, write_filter: Any = None
) -> MemoryRuntime:
    """购物 agent 的 :class:`MemoryRuntime`：按这份配置包装的 store，按 user id 归属，
    用购物场景的提取提示词做提取。"""
    return MemoryRuntime.build(
        config,
        store,
        fence=STOREFRONT_FENCE,
        extraction_prompt=SHOPPING_MEMORY_EXTRACTION_PROMPT,
        write_filter=write_filter,
    )


class ShoppingToolExecutor(BaseToolExecutor):
    fence = STOREFRONT_FENCE
    components = PRESENTATION_COMPONENTS
    displayed_text = "已展示给顾客。"
    unavailable_text = "{name} 暂时不可用。用已有的信息继续，或者告诉顾客。"
    not_offered_text = "{detail}不是本店提供的，请直接告知顾客。"
    sold_out_text = (
        "未加入购物车：{detail}。告知顾客，推荐消息中提到的有货替代品，只有顾客选择后才加入。"
    )
    absent_text = "{name} 不是本店提供的功能；直接说明，不要推荐它。"

    def __init__(
        self,
        *,
        backend: StorefrontBackend,
        config: ShoppingAgentConfig,
        skills: SkillRegistry,
        session: ShoppingSessionContext,
        state: ShoppingSessionState,
        memory: MemoryRuntime | None = None,
    ) -> None:
        super().__init__(
            backend=backend,
            config=config,
            skills=skills,
            session=session,
            state=state,
            memory=memory or build_memory(config, None),
        )

    @property
    def memory_subject(self) -> str:
        return self._session.user_id

    def domain_error(self, error: Exception) -> ToolOutcome | None:
        # 这段消息是围栏外到达的后端文本：清洗并限制长度。
        detail = self._sanitize(str(error), 200)
        if isinstance(error, Unavailable):
            return ToolOutcome.error(self.sold_out_text.format(detail=detail or "不可用"))
        if isinstance(error, NotOffered):
            return ToolOutcome.error(self.not_offered_text.format(detail=detail or "该服务"))
        return None

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

    # ── handler：商品目录 ────────────────────────────────────────────

    async def _search_products(self, tool_input: dict[str, Any]) -> ToolOutcome:
        query = self._sanitize(tool_input.get("query", ""), 300)
        filters = (
            parse_argument(SearchFilters, tool_input["filters"])
            if tool_input.get("filters")
            else None
        )
        limit = self._search_limit(tool_input.get("limit"))
        products = await self._backend.search_products(self._session, query, filters, limit)
        self._state.remember_products(products)
        return ToolOutcome(search_result_text(query, products, self._config.max_fenced_chars))

    async def _get_product_details(self, tool_input: dict[str, Any]) -> ToolOutcome:
        product_id = str(tool_input.get("product_id", ""))
        details = await self._backend.get_product_details(self._session, product_id)
        if details is None:
            return ToolOutcome.error(f"没有 id 为 {product_id} 的商品。")
        # 变体随记录一起进入溯源，购物车才接受它们的 id。
        self._state.remember_products([details, *details.variants])
        return self._fenced(product_details_payload(details))

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
