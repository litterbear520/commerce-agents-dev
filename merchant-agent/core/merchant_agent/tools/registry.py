"""商户 agent 的工具契约，顺序固定。列表只取决于部署配置，所以每次请求发送的字节完全
相同；某项能力能否执行一次调用由执行器判断。一条描述只管一个工具；跨工具的暂存变更约定
放在提示词里，操作流程放在技能里。"""
# 项目中对应 merchant-agent/core/merchant_agent/tools/registry.py
# 省略：status 行（with_status）、get_pending_changes 和暂存写入工具（Step 20）、
# 展示型工具（Step 19）、分析委托（Step 21）、展示扩展、网页搜索、
# INLINE_CONTEXT_DESCRIPTIONS（SDK / MCP 路径用）

from __future__ import annotations

from typing import Any

from commerce_common.execution import LOAD_SKILL

from ..config import MerchantAgentConfig

_SESSION_LISTING_ID = "本次会话中 search_listings 或 get_listing 返回的 listing_id。"


def _listing_id(role: str = _SESSION_LISTING_ID) -> dict[str, Any]:
    return {"type": "string", "description": role}


def _listing_filters_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "description": "经营者说出的条件；query 为空时按这些条件扫描全部商品条目。",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["active", "paused", "draft", "out_of_stock"],
                "description": "要匹配的商品条目状态。",
            },
            "category": {"type": "string", "description": "商品目录分类名。"},
            "max_stock": {
                "type": "integer",
                "minimum": 0,
                "description": "只要库存不高于这个数的商品条目。",
            },
            "content_quality": {
                "type": "string",
                "enum": ["good", "needs_work", "poor"],
                "description": "要匹配的内容质量标记；做内容审查时用 needs_work 或 poor。",
            },
            "sort": {
                "type": "string",
                "enum": ["relevance", "sales_desc", "stock_asc", "price_desc", "price_asc"],
                "description": "结果排序；省略时按相关度。",
            },
        },
        "additionalProperties": False,
    }


def build_tools(
    config: MerchantAgentConfig,
    skill_names: list[str],
) -> list[dict[str, Any]]:
    """一个部署的工具列表：固定顺序的内置工具，去掉配置关掉的系统。"""

    tools: list[dict[str, Any]] = [
        {
            "name": LOAD_SKILL,
            "description": (
                "请求和技能索引里某一条匹配时，加载这个技能的完整规则；然后在整个流程中遵循。"
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
        # ── 经营表现读取 ────────────────────────────────────────────
        {
            "name": "get_business_snapshot",
            "description": (
                "一个周期的核心数字：销售额、订单数、流量、转化率、客单价、和上一周期相比的"
                "变化，以及告警数。任何关于生意做得怎么样的问题，先调它。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "period": {
                        "type": "string",
                        "description": "统计周期，例如 last_7_days、last_30_days，或一个 ISO 日期范围。",
                    },
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "query_metrics",
            "description": (
                "一个指标随时间的变化，可以缩小到某个细分（一个类目、一个商品条目、一个渠道）。"
                "在快照之后用，看趋势、拆分、做对比，或者解释一次变动。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "metric": {
                        "type": "string",
                        "description": "指标名，按快照或序列里的写法。",
                    },
                    "period": {
                        "type": "string",
                        "description": "统计周期，写法同快照；省略时用它的默认值。",
                    },
                    "granularity": {
                        "type": "string",
                        "enum": ["day", "week", "month"],
                        "description": "序列每个点的时间粒度；省略时按天。",
                    },
                    "segment": {
                        "type": "string",
                        "description": "要缩小到的细分；看整体时省略。",
                    },
                },
                "required": ["metric"],
                "additionalProperties": False,
            },
        },
        {
            "name": "get_campaign_performance",
            "description": (
                "营销活动的预算、花费、收入和状态；返回全部，或按 campaign_id 返回一个。"
                "在评估或修改任何营销活动之前先用它。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "campaign_id": {
                        "type": "string",
                        "description": "要返回的那一个营销活动；返回全部时省略。",
                    },
                },
                "additionalProperties": False,
            },
        },
        # ── 商品目录读取 ────────────────────────────────────────────
        {
            "name": "search_listings",
            "description": (
                "搜索商品条目；返回 id、标题、状态、价格、库存和内容质量标记。找具体的东西时用"
                "具体的 query；做审查时用空 query 加 filters 扫描整个目录。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": '要匹配的文字，或者用 "" 浏览全部。',
                    },
                    "filters": _listing_filters_schema(),
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": config.max_search_results,
                        "description": "最多返回几行。",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
        {
            "name": "get_listing",
            "description": (
                "一个商品条目的完整记录：内容、属性、评价摘录、销量、退货率；有选项的商品条目"
                "还带上它的变体，含各变体的 id、价格和库存。在报告、编辑、调价或补货之前先读它；"
                "搜索结果只是摘录，不是完整记录。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {"listing_id": _listing_id("要读取的 listing_id。")},
                "required": ["listing_id"],
                "additionalProperties": False,
            },
        },
        # ── 库存与订单状况 ──────────────────────────────────────────
        {
            "name": "get_inventory_alerts",
            "description": (
                "当前的低库存和滞销告警，带库存量和近期销量。用于每日简报，以及暂存补货之前。"
            ),
            "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "get_order_issues",
            "description": (
                "未处理的订单异常：延迟、退货激增、等待回复的买家留言，每条带一段简短摘录。"
            ),
            "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        # ── 定价读取 ────────────────────────────────────────────────
        {
            "name": "get_pricing_context",
            "description": (
                "一个商品条目或变体的价格、成本和毛利、允许范围、调价上限（永久调价看 "
                "max_price_delta_pct，促销看 max_promotion_discount_pct）和需求信号；有选项的"
                "商品条目每个变体再加一行。在提出任何价格之前先读它；调价只有在范围和两个上限"
                "之内才被允许，被拒绝时会说明违反了哪条限制。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {"listing_id": _listing_id("要定价的 listing_id 或变体 id。")},
                "required": ["listing_id"],
                "additionalProperties": False,
            },
        },
        # ── 记忆 ────────────────────────────────────────────────────
        {
            "name": "save_memory",
            "description": (
                "经营者让你记住一件关于这家店或怎么经营它的事时（品牌语气、定价规则、目标、"
                "季节规律），保存下来。绝不保存商品条目、评价、留言或指标的原文。"
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
                        "description": "要遵守的规则用 constraint；其余用 preference 或 context。",
                    },
                },
                "required": ["key", "value"],
                "additionalProperties": False,
            },
        },
        {
            "name": "recall_memories",
            "description": (
                "搜索不在商户上下文块里的店铺事实：品牌语气、定价规则、季节备注、说过的目标。"
                "只在这样一条事实会改变你写的内容或建议时才调用。"
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

    absent = config.absent_tools()
    return [tool for tool in tools if tool["name"] not in absent]
