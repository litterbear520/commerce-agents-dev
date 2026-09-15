"""购物 agent 的工具定义，顺序固定。列表只取决于部署配置，
因此每次请求发送的字节完全相同；某次调用能否执行由执行器判断。
"""
# 项目中对应 shopping-agent/core/shopping_agent/tools/registry.py
# 当前只包含 6 个基础工具（search + details + cart CRUD）
# 后续加 present_products、checkout、get_orders 等

from __future__ import annotations

from typing import Any

from ..config import ShoppingAgentConfig


def _product_id(description: str = "本次会话中工具返回的 product_id。") -> dict[str, Any]:
    return {"type": "string", "description": description}


def _filters_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "description": "顾客明确提出的筛选条件；猜测的内容放在 query 里。",
        "properties": {
            "category": {"type": "string", "description": "商品目录分类名。"},
            "min_price": {"type": "number", "description": "最低价格。"},
            "max_price": {"type": "number", "description": "顾客说的价格上限。"},
            "min_rating": {"type": "number", "description": "最低评分。"},
            "attributes": {
                "type": "object",
                "description": '属性筛选，键值对形式，如 {"材质": "羊毛"}。',
                "additionalProperties": {"type": "string"},
            },
            "sort": {
                "type": "string",
                "enum": ["relevance", "price_asc", "price_desc", "rating"],
                "description": "排序方式；默认按相关度，除非顾客指定。",
            },
        },
        "additionalProperties": False,
    }


def build_tools(config: ShoppingAgentConfig) -> list[dict[str, Any]]:
    """一个部署的工具列表：固定顺序的内置工具。"""

    tools: list[dict[str, Any]] = [
        {
            "name": "search_products",
            "description": (
                "搜索商品目录，返回商品的 id、标题、品牌、价格、评分和库存状态；"
                "有选项的商品显示最低有货价格和选项列表。"
                "用具体的关键词搜索，把顾客明确说的条件放在 filters 里。"
                "顾客提到多个不同商品时，每个商品单独搜索一次。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "要搜索的关键词，使用商品目录的词汇。",
                    },
                    "filters": _filters_schema(),
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 8,
                        "description": "最多返回几条结果。",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
        {
            "name": "get_product_details",
            "description": (
                "查看一个商品的完整详情：描述、规格参数、评价摘要，"
                "以及有选项的商品的变体列表（含各变体的 id、价格和库存）。"
                "用于回答单个商品的问题、比较候选商品之前选变体、"
                "以及顾客提到类似商品 id 格式的引用时。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "product_id": _product_id("要查看的商品 id。"),
                },
                "required": ["product_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "get_cart",
            "description": "查看当前购物车内容，包括数量和小计。",
            "input_schema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
        {
            "name": "add_to_cart",
            "description": (
                "将商品或所选变体加入购物车，product_id 必须是本次会话中"
                "搜索或详情工具返回的；数量默认为 1。"
                "如果返回说商品不可用，告知顾客并推荐替代品；"
                "只有顾客选择后才加替代品。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "product_id": _product_id(),
                    "quantity": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "要加的件数，不填默认 1。",
                    },
                },
                "required": ["product_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "update_cart_item",
            "description": "修改购物车中已有商品的数量。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "product_id": _product_id("购物车中已有的商品 id。"),
                    "quantity": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "新的数量。",
                    },
                },
                "required": ["product_id", "quantity"],
                "additionalProperties": False,
            },
        },
        {
            "name": "remove_from_cart",
            "description": "从购物车中移除一个商品。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "product_id": _product_id("要移除的商品 id。"),
                },
                "required": ["product_id"],
                "additionalProperties": False,
            },
        },
    ]

    return tools
