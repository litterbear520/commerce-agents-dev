"""商户 agent 的工具契约，顺序固定。列表只取决于部署配置，所以每次请求发送的字节完全
相同；某项能力能否执行一次调用由执行器判断。一条描述只管一个工具；跨工具的暂存变更约定
放在提示词里，操作流程放在技能里。"""
# 项目中对应 merchant-agent/core/merchant_agent/tools/registry.py
# 省略：status 行（with_status）、present_change_preview（Step 20 第 6 组）、
# 分析委托（Step 21）、展示扩展、网页搜索、
# INLINE_CONTEXT_DESCRIPTIONS（SDK / MCP 路径用）

from __future__ import annotations

from typing import Any

from commerce_common.execution import LOAD_SKILL

from ..config import MerchantAgentConfig

_SESSION_LISTING_ID = "本次会话中 search_listings 或 get_listing 返回的 listing_id。"
_ISO_DATE = "ISO 日期（YYYY-MM-DD）。"


def _listing_id(role: str = _SESSION_LISTING_ID) -> dict[str, Any]:
    return {"type": "string", "description": role}


def _change_id() -> dict[str, Any]:
    return {
        "type": "string",
        "description": "本次对话暂存过、或 get_pending_changes 列出过的 change_id。",
    }


def _note(what: str) -> dict[str, Any]:
    return {"type": "string", "maxLength": 200, "description": what}


def _title(what: str) -> dict[str, Any]:
    return {"type": "string", "maxLength": 80, "description": f"{what}的简短标题。"}


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

    # 没有其他 present_* 调用的轮次。stage_shows_preview 打开时，新暂存的建议按钮放在
    # 暂存调用之后的那一轮，和那一句话一起发出。
    chips_alone_cases = "澄清问题、复述商品条目记录"
    if config.stages_changes:
        chips_alone_cases = "护栏说明、" + chips_alone_cases
        if config.stage_shows_preview:
            chips_alone_cases += "、暂存后的那句话"

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
        # ── 审批队列 ────────────────────────────────────────────────
        {
            "name": "get_pending_changes",
            "description": (
                "已暂存、还没应用或丢弃的变更。暂存之前先查它，已经在等待的变更就指出来，"
                "不要再暂存一次。"
            ),
            "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        # ── 暂存写入 ────────────────────────────────────────────────
        {
            "name": "stage_listing_update",
            "description": (
                "暂存对一个商品条目内容或属性的编辑（标题、描述、属性、类目）。返回暂存的"
                "变更；线上的商品条目不会被改动。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "listing_id": _listing_id(),
                    "fields": {
                        "type": "object",
                        "description": '字段名到新值的映射，例如 {"title": "..."}。',
                        "additionalProperties": {"type": ["string", "number"]},
                    },
                    "note": _note("一句话说明这次编辑为什么合适；显示在卡片上。"),
                },
                "required": ["listing_id", "fields"],
                "additionalProperties": False,
            },
        },
        {
            "name": "stage_price_update",
            "description": (
                "为一个或多个商品条目或变体暂存永久调价，价格依据 get_pricing_context；有选项"
                "的商品条目按变体 id 调价，每个变体一个条目。暂存的变更会带回后端算出的调价"
                "前后毛利和毛利影响。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": config.max_items_per_change,
                        "description": "要调价的商品条目或变体，每个一个条目。",
                        "items": {
                            "type": "object",
                            "properties": {
                                "listing_id": _listing_id("listing_id，或一个变体的 id。"),
                                "new_price": {
                                    "type": "number",
                                    "exclusiveMinimum": 0,
                                    "description": "按这个商品条目的币种计的新价格。",
                                },
                            },
                            "required": ["listing_id", "new_price"],
                            "additionalProperties": False,
                        },
                    },
                    "note": _note("一句话说明目标和所做的假设。"),
                },
                "required": ["items"],
                "additionalProperties": False,
            },
        },
        {
            "name": "stage_inventory_action",
            "description": (
                "为一个或多个商品条目暂存补货、暂停或重新上架。补货带上要增加的数量，有选项的"
                "商品条目要指明变体；被预留的库存（保留、冻结）也是通过补货放出来销售的；"
                "数量超过可释放的部分会被拒绝，并附上各项余额。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": config.max_items_per_change,
                        "description": "要操作的商品条目或变体，每个一个条目。",
                        "items": {
                            "type": "object",
                            "properties": {
                                "listing_id": _listing_id("listing_id，或一个变体的 id。"),
                                "action": {
                                    "type": "string",
                                    "enum": ["restock", "pause", "activate"],
                                    "description": "对这个商品条目做什么。",
                                },
                                "quantity": {
                                    "type": "integer",
                                    "minimum": 0,
                                    "description": "要增加的件数；只用于补货。",
                                },
                            },
                            "required": ["listing_id", "action"],
                            "additionalProperties": False,
                        },
                    },
                    "note": _note("一句话说明理由，数字取自告警。"),
                },
                "required": ["items"],
                "additionalProperties": False,
            },
        },
        {
            "name": "stage_promotion",
            "description": (
                "为一组商品条目暂存有时限的调价；每个促销都有结束日期。任何只限特定日期的"
                "调价都用它，涨价也一样。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "maxLength": 80,
                        "description": "经营者在队列里能认出来的名字。",
                    },
                    "listing_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": config.max_items_per_change,
                        "minItems": 1,
                        "description": "范围内的商品条目，取自本次会话的商品目录读取。",
                    },
                    "discount_pct": {
                        "type": "number",
                        "minimum": -90,
                        "maximum": 90,
                        "description": "这段时间的折扣百分比；负数表示涨价。",
                    },
                    "starts": {"type": "string", "description": f"第一天，{_ISO_DATE}"},
                    "ends": {"type": "string", "description": f"最后一天，{_ISO_DATE}"},
                    "nights": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
                        },
                        "description": "把调价限制在一周中的这几个晚上。",
                    },
                },
                "required": ["name", "listing_ids", "discount_pct", "starts", "ends"],
                "additionalProperties": False,
            },
        },
        {
            "name": "stage_campaign",
            "description": (
                "暂存一个营销活动草稿（名称、目标、受众、预算、文案、日期），或者对已有 "
                "campaign_id 的预算或文案修改。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "campaign_id": {
                        "type": "string",
                        "description": "要修改的已有营销活动；新草稿时省略。",
                    },
                    "name": {
                        "type": "string",
                        "maxLength": 80,
                        "description": "营销活动名称。",
                    },
                    "objective": {
                        "type": "string",
                        "maxLength": 200,
                        "description": "这个活动要推动的那一个可衡量指标。",
                    },
                    "audience": {
                        "type": "string",
                        "maxLength": 300,
                        "description": "要触达的人群，按意图来写。",
                    },
                    "budget": {
                        "type": "number",
                        "minimum": 0,
                        "description": "按店铺币种计的总预算。",
                    },
                    "copy_text": {
                        "type": "string",
                        "maxLength": 600,
                        "description": "文案草稿，事实取自商品条目记录。",
                    },
                    "starts": {"type": "string", "description": f"第一天，{_ISO_DATE}"},
                    "ends": {"type": "string", "description": f"最后一天，{_ISO_DATE}"},
                },
                "required": ["name"],
                "additionalProperties": False,
            },
        },
        {
            "name": "apply_change",
            "description": (
                "应用一条经营者已经在你的指令所指定的审批界面上审批通过的暂存变更。"
                "这是唯一会改动线上状态的调用。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {"change_id": _change_id()},
                "required": ["change_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "discard_change",
            "description": (
                "丢弃一条经营者决定不要、或已经不再考虑的暂存变更，并说明这一点；不要反过来"
                "劝对方应用它。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {"change_id": _change_id()},
                "required": ["change_id"],
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
    presentation: list[dict[str, Any]] = [
        {
            "name": "present_metrics",
            "description": (
                "把工具返回的度量展示成指标卡和趋势线；数值由门户填入。每个指标按工具的写法"
                "命名，或者写成营销活动 id 加一个度量（'<campaign_id> spend'，或 revenue、"
                "budget、roas）。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "title": _title("卡片"),
                    "period": {
                        "type": "string",
                        "maxLength": 80,
                        "description": "这些数字覆盖的周期，照查询时的写法。",
                    },
                    "picks": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 8,
                        "description": "要展示的度量，结论最重要的放第一个。",
                        "items": {
                            "type": "object",
                            "properties": {
                                "metric": {
                                    "type": "string",
                                    "maxLength": 60,
                                    "description": "度量名，照工具返回的写法。",
                                },
                                "note": {
                                    "type": "string",
                                    "maxLength": 140,
                                    "description": "一句话说明这个度量为什么重要。",
                                },
                            },
                            "required": ["metric"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["picks"],
                "additionalProperties": False,
            },
        },
        {
            "name": "present_digest",
            "description": (
                "展示需要关注的摘要：告警、订单异常、指标变动和待审变更，排好优先级，每条说明"
                "为什么重要。经营者要简报或问有什么要处理时使用；用 id 指代条目。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "title": _title("摘要"),
                    "items": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 8,
                        "description": "按优先级排列的条目。",
                        "items": {
                            "type": "object",
                            "properties": {
                                "kind": {
                                    "type": "string",
                                    "enum": [
                                        "low_stock",
                                        "slow_mover",
                                        "order_issue",
                                        "metric",
                                        "pending_change",
                                        "note",
                                    ],
                                    "description": "条目类型；收尾的总结句用 note。",
                                },
                                "ref_id": {
                                    "type": "string",
                                    "maxLength": 64,
                                    "description": "涉及的商品条目、订单异常或变更的 id。",
                                },
                                "headline": {
                                    "type": "string",
                                    "maxLength": 120,
                                    "description": "出了什么问题，带上工具结果里的数字。",
                                },
                                "why_it_matters": {
                                    "type": "string",
                                    "maxLength": 160,
                                    "description": "代价或期限，以及下一步动作。",
                                },
                            },
                            "required": ["kind", "headline"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["items"],
                "additionalProperties": False,
            },
        },
        {
            "name": "present_suggestions",
            "description": (
                "给这一轮添加 1-4 个建议按钮，调用后结束回复。和本轮最后一个 present_* 调用"
                "在同一轮发出，不用等那个调用的结果。单独使用时放在文字之后，只在没有其他 "
                f"present_* 调用的轮次使用（{chips_alone_cases}）。"
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
                            "1-4 条建议，每条是简短的祈使句，把工作再往前推一步；"
                            "不要重复本轮已展示的内容。"
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
