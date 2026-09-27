"""部署级别的商户 agent 配置；每次请求的值通过 ``MerchantSessionContext`` 传入。
各节接着 ``BaseAgentConfig`` 的顺序往下写：能力（分析）、护栏、审批、数据锚定门控。"""
# 项目中对应 merchant-agent/core/merchant_agent/config.py
# 省略：thinking_effort 覆盖为 "low"（dev 保持基类的 None）；
# 分析委托（Step 21）；护栏、审批、stages_changes（Step 20）；
# 数据锚定门控里的跟进提醒和审批队列两组（Step 20）

from __future__ import annotations

from commerce_common.config import BaseAgentConfig


class MerchantAgentConfig(BaseAgentConfig):
    assistant_name: str = "商户助手"
    brand_voice: str = "直白具体，数字优先"
    # 源码默认 claude-opus-5；dev 环境用 DeepSeek 统一模型
    model: str = "deepseek-v4-flash"

    # ── 店铺运营的系统。指标和商品目录的读取是最低要求；以下开关关掉时，对应系统的
    # 读取和暂存工具在所有路径上都不存在，适用于根本没有该系统的商家。系统存在但还没
    # 接上的保持开启：它的后端方法抛出 ChangeNotApplicable，工具如实说明。
    enable_listing_edits: bool = True
    enable_inventory: bool = True
    enable_pricing: bool = True
    enable_campaigns: bool = True

    def absent_tools(self) -> frozenset[str]:
        """``build_tools`` 为上面关掉的系统排除掉的工具名。"""
        # 省略：各系统的 stage_* 工具和变更队列工具（Step 20）
        names: set[str] = set()
        if not self.enable_inventory:
            names |= {"get_inventory_alerts", "get_order_issues"}
        if not self.enable_pricing:
            names |= {"get_pricing_context"}
        if not self.enable_campaigns:
            names |= {"get_campaign_performance"}
        return frozenset(names)

    # ── 数据锚定门控（由运行时读取）。指标：一个业绩词加一个疑问线索，强制调用
    # get_business_snapshot。
    # 中文词条跟在英文词条后面：matches_any 对不含拉丁字母的词条按子串匹配，
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
        "怎么样",
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
