"""购物 agent 的工具定义，顺序固定。列表只取决于部署配置，
因此每次请求发送的字节完全相同；某次调用能否执行由执行器判断。
一条描述只管一个工具；跨工具的规则放在提示词或技能里。
"""
# 项目中对应 shopping-agent/core/shopping_agent/tools/registry.py

from __future__ import annotations

from typing import Any

from commerce_common.execution import LOAD_SKILL

from ..config import ShoppingAgentConfig

_SESSION_PRODUCT_ID = "本次会话中工具返回的 product_id。"


def _product_id(role: str = _SESSION_PRODUCT_ID) -> dict[str, Any]:
    return {"type": "string", "description": role}


def _title(what: str) -> dict[str, Any]:
    return {"type": "string", "maxLength": 80, "description": f"{what}的简短标题。"}


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


def build_tools(
    config: ShoppingAgentConfig,
    skill_names: list[str],
) -> list[dict[str, Any]]:
    """一个部署的工具列表：固定顺序的内置工具，去掉配置关掉的系统。"""

    tools: list[dict[str, Any]] = [
        {
            "name": LOAD_SKILL,
            "description": (
                "加载技能索引中与当前请求匹配的流程规则；规则不在你的提示词里。"
                "在该流程首次读取数据的同一轮调用，并在整个流程中遵循。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "skill_name": {
                        "type": "string",
                        "enum": sorted(skill_names),
                        "description": "索引中列出的技能名称。",
                    },
                },
                "required": ["skill_name"],
                "additionalProperties": False,
            },
        },
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
        {
            "name": "get_preferences",
            "description": (
                "当前顾客的个人资料和偏好。通常已在会话上下文里；只有上下文缺失时才调用。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
        {
            "name": "get_orders",
            "description": (
                "最近的订单及状态和预计送达时间。"
                "用于没有指定订单号的状态查询，以及顾客要再次购买的场景。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 20,
                        "description": "最多返回几张订单。",
                    },
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "get_order_status",
            "description": "顾客指定的一张订单的状态、商品和物流信息。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "要查看的订单号。",
                    },
                },
                "required": ["order_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "search_policies",
            "description": (
                "搜索本店的条款和帮助内容：退换货、运费、保修、会员权益、费用说明和选购指南。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "要查找的条款或主题。",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
        {
            "name": "get_fulfillment_options",
            "description": "指定商品在顾客所在地的配送和自提选项，含预计到达时间。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "product_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 20,
                        "description": "要查配送选项的商品 id。",
                    },
                },
                "required": ["product_ids"],
                "additionalProperties": False,
            },
        },
        {
            "name": "save_memory",
            "description": (
                "顾客让你记住某件事、或说出一条长期适用的购物规则时，保存一条关于他的长期事实。"
                '"记住我……"这类请求属于 memory-personalization 流程，事实该怎么措辞由那个技能'
                "规定：在同一轮里读它。保存商品背后反映出的需求，不要保存商品或条款的原文。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "maxLength": 64,
                        "description": "主题 key；沿用已有的 key 会覆盖它的值。",
                    },
                    "value": {
                        "type": "string",
                        "maxLength": 200,
                        "description": "事实本身，措辞要保证以后单独拿出来也看得懂。",
                    },
                    "category": {
                        "type": "string",
                        "enum": ["preference", "constraint", "context"],
                        "description": (
                            "选品必须遵守的规则用 constraint；其余用 preference 或 context。"
                        ),
                    },
                },
                "required": ["key", "value"],
                "additionalProperties": False,
            },
        },
        {
            "name": "recall_memories",
            "description": (
                "搜索不在会话上下文块里的顾客事实：更早的偏好、尺码、以前送礼的对象、"
                "周期性的需求。只在这样一条事实会改变你的推荐时才调用。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "maxLength": 100,
                        "description": "要搜索的主题，几个词。",
                    },
                },
                "required": ["topic"],
                "additionalProperties": False,
            },
        },
    ]

    # ── 展示型工具 ──────────────────────────────────────────────────

    presentation: list[dict[str, Any]] = [
        {
            "name": "present_products",
            "description": (
                "把本次会话搜索结果中的商品展示为卡片；标题、价格、图片由服务端补全。"
                "布局默认轮播，grid 适合浏览多个选项，list 适合顺序重要的场景。"
                "每个 pick 的 reason 是你对这张卡片的唯一判断。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "title": _title("卡片组"),
                    "layout": {
                        "type": "string",
                        "enum": ["carousel", "grid", "list"],
                        "description": "卡片布局；不填默认轮播。",
                    },
                    "picks": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 12,
                        "description": "要展示的商品，推荐的排在前面。",
                        "items": {
                            "type": "object",
                            "properties": {
                                "product_id": _product_id(),
                                "reason": {
                                    "type": "string",
                                    "maxLength": 140,
                                    "description": "一句话说明为什么选这个商品。",
                                },
                            },
                            "required": ["product_id"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["picks"],
                "additionalProperties": False,
            },
        },
        {
            "name": "present_comparison",
            "description": (
                "把 2-4 个候选商品并排对比，列出优缺点和各自适合的场景。"
                "在顾客已经缩小范围或问它们有什么区别时使用；"
                "新的推荐列表用 present_products。"
                "服务端会补上价差；你的文本说明多花的钱买到了什么。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "title": _title("对比表"),
                    "entries": {
                        "type": "array",
                        "minItems": 2,
                        "maxItems": 4,
                        "description": "要对比的候选商品。",
                        "items": {
                            "type": "object",
                            "properties": {
                                "product_id": _product_id(),
                                "pros": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "maxItems": 4,
                                    "description": "简短的优点，来自工具返回的数据。",
                                },
                                "cons": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "maxItems": 3,
                                    "description": "简短的缺点，来自工具返回的数据。",
                                },
                                "best_for": {
                                    "type": "string",
                                    "maxLength": 80,
                                    "description": "这个选项最适合谁或什么场景。",
                                },
                            },
                            "required": ["product_id"],
                            "additionalProperties": False,
                        },
                    },
                    "dimensions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 6,
                        "description": "顾客在权衡的维度。",
                    },
                    "recommended_product_id": _product_id("你推荐的那个商品。"),
                },
                "required": ["entries"],
                "additionalProperties": False,
            },
        },
        {
            "name": "present_plan",
            "description": (
                "把顾客的目标拆成分步计划，每一步可以关联商品。"
                "如果没有任何步骤会关联商品，说明这是知识性内容，用 present_guide。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "title": _title("计划"),
                    "intro": {
                        "type": "string",
                        "maxLength": 240,
                        "description": "一两句话交代背景和前提。",
                    },
                    "steps": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 12,
                        "description": "计划的步骤，按执行顺序排列。",
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {
                                    "type": "string",
                                    "maxLength": 120,
                                    "description": "用顾客的话描述这一步。",
                                },
                                "detail": {
                                    "type": "string",
                                    "maxLength": 240,
                                    "description": "一句话说明这一步涉及什么。",
                                },
                                "product_ids": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "maxItems": 8,
                                    "description": "这一步需要的商品，推荐的排在前面。",
                                },
                            },
                            "required": ["label"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["title", "steps"],
                "additionalProperties": False,
            },
        },
        {
            "name": "present_guide",
            "description": (
                "用分节卡片展示操作指南、选购建议或行程规划。"
                "用于不涉及商品计划的知识性内容；"
                "引用了网页内容时列出来源。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "title": _title("指南"),
                    "sections": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 8,
                        "description": "每节一到三句话。",
                        "items": {
                            "type": "object",
                            "properties": {
                                "heading": {
                                    "type": "string",
                                    "maxLength": 80,
                                    "description": "小节标题。",
                                },
                                "body": {
                                    "type": "string",
                                    "maxLength": 600,
                                    "description": "小节正文。",
                                },
                            },
                            "required": ["heading", "body"],
                            "additionalProperties": False,
                        },
                    },
                    "related_product_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 8,
                        "description": "本次会话中与指南相关的商品。",
                    },
                    "sources": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 5,
                        "description": "内容引用的指南或页面。",
                    },
                },
                "required": ["title", "sections"],
                "additionalProperties": False,
            },
        },
        {
            "name": "present_order_status",
            "description": (
                "展示一张订单的状态卡片；订单数据由服务端补全。"
                "每次回答订单进度都走这个卡片。多张在途订单时，同一轮每张订单各发一张卡片。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "get_orders 或 get_order_status 返回的订单号。",
                    },
                    "summary": {
                        "type": "string",
                        "maxLength": 300,
                        "description": "当前状态和预计日期，一句话。",
                    },
                    "next_step": {
                        "type": "string",
                        "maxLength": 200,
                        "description": "顾客现在能做的一件具体的事。",
                    },
                },
                "required": ["order_id", "summary"],
                "additionalProperties": False,
            },
        },
        {
            "name": "checkout",
            "description": (
                "把当前购物车作为订单摘要展示给顾客确认；"
                "不会下单也不会扣款。只在顾客要求结账时使用。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "note": {
                        "type": "string",
                        "maxLength": 300,
                        "description": "顾客确认前需要注意的事项。",
                    },
                    "fulfillment_method": {
                        "type": "string",
                        "enum": ["delivery", "pickup", "shipping"],
                        "description": "顾客选择的配送方式。",
                    },
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "present_suggestions",
            "description": (
                "给这一轮对话添加 1-4 个建议按钮，调用后结束回复。"
                "和本轮最后一个展示组件在同一轮调用，不用等那个组件的结果。"
                "单独使用时放在文本之后，只在没有展示组件的轮次使用"
                "（比如回答条款问题、澄清确认、确认加购）。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "suggestions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "maxItems": 4,
                        "description": (
                            "1-4 条建议，每条是简短的祈使句，"
                            "方向各不相同；不要重复本轮已展示的内容。"
                        ),
                    },
                },
                "required": ["suggestions"],
                "additionalProperties": False,
            },
        },
    ]

    absent = config.absent_tools()
    tools = [tool for tool in tools if tool["name"] not in absent]
    tools += [tool for tool in presentation if tool["name"] not in absent]

    return tools
