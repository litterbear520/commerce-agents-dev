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

from .backend import NotOffered, StorefrontBackend, Unavailable
from .config import ShoppingAgentConfig
from .fencing import STOREFRONT_FENCE
from .outcome import ToolOutcome
from .types import SearchFilters, ShoppingSessionContext, ShoppingSessionState

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
    ) -> None:
        self._backend = backend
        self._config = config
        self._session = session
        self._state = state
        self._handlers: dict[str, Handler] = self._build_handlers()

    def _build_handlers(self) -> dict[str, Handler]:
        return {
            "search_products": self._search_products,
            "get_product_details": self._get_product_details,
            "get_cart": self._get_cart,
            "add_to_cart": self._add_to_cart,
            "update_cart_item": self._update_cart_item,
            "remove_from_cart": self._remove_from_cart,
        }

    # ── execute / dispatch ───────────────────────────────────────────

    async def execute(self, name: str, tool_input: dict[str, Any] | None) -> ToolOutcome:
        # 执行一次工具调用，永远不会抛异常
        # 分级异常处理：领域异常（Unavailable / NotOffered）→ 兜底 "暂时不可用"
        try:
            return await self.dispatch(name, dict(tool_input or {}))
        except Exception as error:
            if (outcome := self._domain_error(error)) is not None:
                return outcome
            logger.warning("tool %s failed", name, exc_info=True)
            return ToolOutcome.error(f"{name} 暂时不可用，请用已有的信息继续。")

    async def dispatch(self, name: str, tool_input: dict[str, Any]) -> ToolOutcome:
        """不带异常包裹的分派：异常会向上传播。"""
        handler = self._handlers.get(name)
        if handler is None:
            return ToolOutcome.error(f"未知工具：{name}")
        return await handler(tool_input)

    def _domain_error(self, error: Exception) -> ToolOutcome | None:
        # 项目中对应 ShoppingToolExecutor.domain_error
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
        self._state.remember_products([details, *details.variants])
        return self._fenced(details.model_dump(exclude_none=True))

    # ── handler：购物车 ──────────────────────────────────────────────

    async def _get_cart(self, _: dict[str, Any]) -> ToolOutcome:
        cart = await self._backend.get_cart(self._session)
        return self._fenced(cart.model_dump(exclude_none=True))

    async def _add_to_cart(self, tool_input: dict[str, Any]) -> ToolOutcome:
        # 门控逻辑在 gates.py 里，这里先直接调后端（Step 07 gates.py 会串起来）
        from .gates import gated_add_to_cart

        return await gated_add_to_cart(
            backend=self._backend,
            config=self._config,
            session=self._session,
            state=self._state,
            product_id=str(tool_input.get("product_id", "")),
            quantity=int(tool_input.get("quantity") or 1),
        )

    async def _update_cart_item(self, tool_input: dict[str, Any]) -> ToolOutcome:
        from .gates import gated_update_cart_item

        return await gated_update_cart_item(
            backend=self._backend,
            config=self._config,
            session=self._session,
            state=self._state,
            product_id=str(tool_input.get("product_id", "")),
            quantity=int(tool_input.get("quantity") or 1),
        )

    async def _remove_from_cart(self, tool_input: dict[str, Any]) -> ToolOutcome:
        from .gates import gated_remove_from_cart

        return await gated_remove_from_cart(
            backend=self._backend,
            session=self._session,
            state=self._state,
            product_id=str(tool_input.get("product_id", "")),
        )
