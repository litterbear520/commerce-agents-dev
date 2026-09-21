"""部署级别的购物 agent 配置；每次请求的值通过 ``ShoppingSessionContext`` 传入。
各节延续 ``BaseAgentConfig`` 的顺序：购物车上限、数据锚定门控。"""
# 项目中对应 shopping-agent/core/shopping_agent/config.py
# 项目中 ShoppingAgentConfig 继承 commerce_common 的 BaseAgentConfig，
# Step 17 迁到 commerce_common 时再拆出基类

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ThinkingEffort = Literal["low", "medium", "high", "xhigh", "max"]


class ShoppingAgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # ── 身份（写入提示词）────────────────────────────────────────────
    brand_name: str = "ACME 商店"
    assistant_name: str = "购物助手"
    brand_voice: str = "热情、简洁，坦诚说明优缺点"

    # ── 模型 ────────────────────────────────────────────────────────
    model: str = "deepseek-v4-flash"
    max_tokens: int = 2048
    max_tool_iterations: int = 8
    request_timeout_s: float = 120.0
    thinking_effort: ThinkingEffort | None = None

    # ── 延迟优化开关。每个开关独立关闭，可以逐个排查延迟问题 ────────────
    eager_tool_dispatch: bool = True
    rolling_conversation_cache: bool = True
    eager_partial_frames: bool = False
    close_on_presentation: bool = True

    # ── 上限 ────────────────────────────────────────────────────────
    max_context_chars: int = Field(default=2000, ge=0)
    compact_history_above_tokens: int = Field(default=100_000, ge=0)

    # ── 能力开关。网页搜索加一个工具（提示词）；记忆工具始终注册，
    # ``enable_memory`` 切换它们在所有路径上的行为。
    enable_memory: bool = True

    # ── 记忆参数：每次请求注入的事实数（所有 constraint + 最近的），
    # 在默认拦截正则之上的额外写入过滤正则（flag 内联），
    # 以及事实过期天数（None 永不过期）。
    # 源码默认 claude-haiku-4-5-20251001；dev 环境用 DeepSeek 统一模型
    memory_model: str = "deepseek-v4-flash"
    memory_tier_one_cap: int = Field(default=8, ge=0)
    memory_blocked_patterns: tuple[str, ...] = ()
    memory_retention_days: int | None = Field(default=None, ge=1)

    # ── 上限：围栏后的工具结果最大字符数。
    max_fenced_chars: int = 12_000

    # ── 店铺拥有的子系统。搜索和商品详情是最低要求；以下开关关掉时，
    # 对应的工具、提示词行和数据锚定规则在所有路径上都不存在，
    # 适用于根本没有该子系统的店铺。子系统存在但还没接上的保持开启：
    # 它的后端方法会抛异常，工具则回答该功能不可用。
    enable_cart: bool = True
    enable_orders: bool = True
    enable_policies: bool = True
    enable_fulfillment: bool = True

    # ── 购物车上限，由门控在所有路径上统一执行 ────────────────────────
    max_quantity_per_item: int = Field(default=24, ge=1)
    max_cart_lines: int = Field(default=100, ge=1)

    # ── 数据锚定门控（由运行时读取）：消息匹配时，每条规则在本轮第一次迭代
    # 强制一次读取。部署方通过扩展词汇表加入自己领域的词汇。
    # ID 正则最多匹配四位数字，这样五位的订单号走订单规则；
    # "delivered" 不在订单意图词里，因为它在普通购物对话中也会出现。
    policy_grounding_gate: bool = True
    policy_intent_terms: tuple[str, ...] = (
        "return",
        "returns",
        "refund",
        "refunds",
        "exchange",
        "exchanges",
        "warranty",
        "guarantee",
        "cancel",
        "cancellation",
        "restocking",
        "fee",
        "fees",
        "shipping cost",
        "shipping costs",
        "delivery cost",
        "price match",
        "price lock",
        "membership",
        "subscription",
        "contract",
        "policy",
        "policies",
        "terms",
    )
    policy_intent_cues: tuple[str, ...] = (
        "?",
        "how",
        "what",
        "when",
        "can i",
        "could i",
        "do you",
        "does",
        "is there",
        "tell me",
        "explain",
        "how long",
        "how much",
    )
    order_grounding_gate: bool = True
    order_intent_terms: tuple[str, ...] = (
        "order",
        "orders",
        "delivery",
        "delivery address",
        "package",
        "parcel",
        "shipment",
        "tracking",
        "tracking number",
    )
    order_intent_cues: tuple[str, ...] = (
        "?",
        "where",
        "when",
        "status",
        "cancel",
        "change",
        "return",
        "refund",
        "late",
        "arrive",
        "arrived",
        "track",
        "missing",
        "damaged",
        "hasn't",
        "delayed",
    )
    catalog_grounding_gate: bool = True
    product_id_patterns: tuple[str, ...] = (
        r"\b[A-Z]{2,4}-\d{3,4}\b",
        r"\b[A-Z]{2,4}-[A-Z]{2,6}-\d{2,4}(?:-[A-Z0-9]{2,6})?\b",
    )

    def thinking_request_fields(self) -> dict[str, Any]:
        """模型调用携带的 thinking 请求字段。"""
        if self.thinking_effort is None:
            return {"thinking": {"type": "disabled"}}
        return {
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": self.thinking_effort},
        }

    def absent_tools(self) -> frozenset[str]:
        """``build_tools`` 为上面关掉的子系统排除掉的工具名。"""
        names: set[str] = set()
        if not self.enable_cart:
            names |= {"get_cart", "add_to_cart", "update_cart_item", "remove_from_cart", "checkout"}
        if not self.enable_orders:
            names |= {"get_orders", "get_order_status", "present_order_status"}
        if not self.enable_policies:
            names.add("search_policies")
        if not self.enable_fulfillment:
            names.add("get_fulfillment_options")
        return frozenset(names)
