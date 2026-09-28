"""部署级别的商户 agent 配置；每次请求的值通过 ``MerchantSessionContext`` 传入。
各节接着 ``BaseAgentConfig`` 的顺序往下写：能力（分析）、护栏、审批、数据锚定门控。"""
# 项目中对应 merchant-agent/core/merchant_agent/config.py
# 省略：分析委托（Step 21）；数据锚定门控里的跟进提醒和审批队列两组（Step 20）

from __future__ import annotations

from pydantic import Field

from commerce_common.config import BaseAgentConfig, ThinkingEffort


class MerchantAgentConfig(BaseAgentConfig):
    assistant_name: str = "商户助手"
    brand_voice: str = "直白具体，数字优先"
    # 源码默认 claude-opus-5；dev 环境用 DeepSeek 统一模型
    model: str = "deepseek-v4-flash"
    thinking_effort: ThinkingEffort | None = "low"

    # ── 店铺运营的系统。指标和商品目录的读取是最低要求；以下开关关掉时，对应系统的
    # 读取和暂存工具在所有路径上都不存在，适用于根本没有该系统的商家。写入全部关掉时，
    # 变更队列（get_pending_changes、apply_change、discard_change、预览卡）也一起去掉。
    # 系统存在但还没接上的保持开启：它的后端方法抛出 ChangeNotApplicable，工具如实说明。
    enable_listing_edits: bool = True
    enable_inventory: bool = True
    enable_pricing: bool = True
    enable_campaigns: bool = True

    # ── 护栏，暂存时检查一次，应用前再检查一次。某个领域用别的名字定价时，
    # `price_bearing_fields` 和 `listing_update_blocked_fields` 只追加、不替换。
    # `max_items_per_change` 数的是经营者要审批的行数，所以对 family 的促销按展开后的
    # 每个变体各算一次。
    max_items_per_change: int = Field(default=25, ge=1)
    max_price_delta_pct: float = Field(default=20.0, gt=0)
    max_promotion_discount_pct: float = Field(default=50.0, gt=0, le=90)
    max_restock_quantity: int = Field(default=500, ge=1)
    max_campaign_budget: float = Field(default=10_000.0, gt=0)
    max_listing_field_chars: int = Field(default=2000, ge=200)
    protected_fields: tuple[str, ...] = (
        "listing_id",
        "currency",
        "tax_category",
        "compliance_notes",
    )
    price_bearing_fields: tuple[str, ...] = ("price",)
    listing_update_blocked_fields: tuple[str, ...] = ("price", "stock")

    # ── 审批（提示词）。`require_host_approval` 打开时，apply_change 只对调用方在
    # MerchantSessionState.approved_change_ids 上标记过的 id 成功；信任对话流程的部署
    # 可以关掉。`approval_surface` 是调用方审批入口的叫法，用在拒绝消息和提示词指引里。
    # `stage_shows_preview` 打开时，stage_* 调用成功后自己渲染变更预览卡（提示词和工具
    # 文本会这么说）；执行器事件到不了经营者的部署（MCP 服务器）把它关掉，由模型用
    # present_change_preview 展示变更。
    require_host_approval: bool = True
    approval_surface: str = "调用方应用里的审批控件"
    stage_shows_preview: bool = True

    # ── 数据锚定门控（由运行时读取）。指标：一个业绩词加一个疑问线索，强制调用
    # get_business_snapshot。
    # 中文词条跟在英文词条后面：matches_any 对不含拉丁字母和数字的词条按子串匹配，
    # 所以这里写的是词而不是整句，"卖" 这类单字不收，避免在无关句子里误触发。
    metrics_grounding_gate: bool = True
    metrics_intent_terms: tuple[str, ...] = (
        "sales",
        "revenue",
        "orders",
        "traffic",
        "conversion",
        "aov",
        "average order value",
        "performance",
        "performing",
        "trend",
        "trending",
        "growth",
        "drop",
        "dropped",
        "spike",
        "returns rate",
        "return rate",
        "margin",
        "margins",
        "profit",
        "best seller",
        "best sellers",
        "slow mover",
        "slow movers",
        "sell-through",
        "campaign performance",
        "ad spend",
        "return on ad spend",
        "roas",
        "销售",
        "销量",
        "卖得",
        "营业额",
        "收入",
        "订单",
        "流量",
        "访客",
        "转化",
        "客单价",
        "业绩",
        "表现",
        "趋势",
        "增长",
        "下滑",
        "下降",
        "暴涨",
        "退货率",
        "利润",
        "毛利",
        "畅销",
        "滞销",
        "售罄率",
        "广告花费",
        "投产比",
    )
    metrics_intent_cues: tuple[str, ...] = (
        "?",
        "how",
        "what",
        "why",
        "show me",
        "compare",
        "summarize",
        "summary",
        "report",
        "this week",
        "last week",
        "this month",
        "last month",
        "yesterday",
        "today",
        "vs",
        "versus",
        "？",
        "怎么",
        "如何",
        "为什么",
        "多少",
        "看看",
        "对比",
        "比较",
        "总结",
        "汇总",
        "报告",
        "本周",
        "这周",
        "上周",
        "本月",
        "这个月",
        "上个月",
        "昨天",
        "今天",
    )

    @property
    def stages_changes(self) -> bool:
        """这个部署是否还剩下任何 stage_* 工具。"""
        return (
            self.enable_listing_edits
            or self.enable_inventory
            or self.enable_pricing
            or self.enable_campaigns
        )

    def absent_tools(self) -> frozenset[str]:
        """``build_tools`` 为上面关掉的系统排除掉的工具名。"""
        names: set[str] = set()
        if not self.enable_listing_edits:
            names.add("stage_listing_update")
        if not self.enable_inventory:
            names |= {"get_inventory_alerts", "get_order_issues", "stage_inventory_action"}
        if not self.enable_pricing:
            names |= {"get_pricing_context", "stage_price_update", "stage_promotion"}
        if not self.enable_campaigns:
            names |= {"get_campaign_performance", "stage_campaign"}
        if not self.stages_changes:
            names |= {
                "get_pending_changes",
                "apply_change",
                "discard_change",
                "present_change_preview",
            }
        return frozenset(names)
