"""部署级别的购物 agent 配置；每次请求的值通过 ``ShoppingSessionContext`` 传入。
各节接着 ``BaseAgentConfig`` 的顺序往下写：能力、购物车上限、数据锚定门控。"""
# 项目中对应 shopping-agent/core/shopping_agent/config.py
# 省略：thinking_effort 覆盖为 "low"（dev 保持基类的 None）；
# domain_search_notes、enable_disclosures（后续步骤用到时再加）

from __future__ import annotations

from pydantic import Field

from commerce_common.config import BaseAgentConfig


class ShoppingAgentConfig(BaseAgentConfig):
    assistant_name: str = "购物助手"
    brand_voice: str = "热情、简洁，坦诚说明优缺点"
    # 源码默认 claude-sonnet-5；dev 环境用 DeepSeek 统一模型
    model: str = "deepseek-v4-flash"

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
    # 中文词条跟在英文词条后面：matches_any 对不含拉丁字母的词条按子串匹配，
    # 所以这里写的是词而不是整句，"退" 这类单字不收，避免在无关句子里误触发。
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
        "退货",
        "退款",
        "退换",
        "换货",
        "保修",
        "质保",
        "取消",
        "手续费",
        "运费",
        "邮费",
        "会员",
        "订阅",
        "条款",
        "政策",
        "规定",
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
        "？",
        "怎么",
        "如何",
        "能不能",
        "可以",
        "多久",
        "多少",
        "什么",
        "有没有",
        "是不是",
        "说说",
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
        "订单",
        "快递",
        "包裹",
        "物流",
        "运单",
        "收货地址",
        "发货",
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
        "？",
        "哪",
        "什么时候",
        "多久",
        "状态",
        "取消",
        "修改",
        "退货",
        "退款",
        "到了",
        "查",
        "丢",
        "破损",
        "延迟",
        "还没",
    )
    catalog_grounding_gate: bool = True
    product_id_patterns: tuple[str, ...] = (
        r"\b[A-Z]{2,4}-\d{3,4}\b",
        r"\b[A-Z]{2,4}-[A-Z]{2,6}-\d{2,4}(?:-[A-Z0-9]{2,6})?\b",
    )

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
