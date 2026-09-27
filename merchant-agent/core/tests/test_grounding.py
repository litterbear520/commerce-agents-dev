"""数据锚定规则把一个轮次固定到哪次读取上。"""
# 项目中对应 merchant-agent/core/tests/test_grounding.py
# 省略：审批队列规则（apply 句子、优先级、会话已有暂存变更时让位）和跟进提醒检测
# change_requested 的用例（Step 20）

import pytest

from commerce_common.grounding import first_forced_tool
from merchant_agent import MerchantSessionState
from merchant_agent.grounding import GROUNDING_RULES


def forced(config, text: str, state: MerchantSessionState | None = None) -> str | None:
    return first_forced_tool(GROUNDING_RULES, config, text, state or MerchantSessionState())


# 英文语料：默认词表的英文词条走全词边界（``\b``）匹配，要用英文句子才测得到；
# 中文词条走子串匹配，在下一组单独测。
@pytest.mark.parametrize(
    ("text", "tool"),
    [
        ("How were sales last week?", "get_business_snapshot"),
        ("What's the conversion trend?", "get_business_snapshot"),
        # 项目中还有三条 apply 句子强制 get_pending_changes，Step 20 再加
    ],
)
def test_performance_questions_and_apply_requests_each_force_their_read(config, text, tool):
    assert forced(config, text) == tool


@pytest.mark.parametrize(
    ("text", "tool"),
    [
        ("上周卖得怎么样？", "get_business_snapshot"),
        ("这个月的转化率为什么下滑了", "get_business_snapshot"),
        ("对比一下本周和上周的订单", "get_business_snapshot"),
    ],
)
def test_chinese_messages_force_the_same_reads(config, text, tool):
    assert forced(config, text) == tool


@pytest.mark.parametrize(
    "text",
    [
        "Anything urgent this morning?",
        "Set the planter price to $17.50.",
        "The price we settled on yesterday, applying it now.",
        "Go ahead and stage the markdown you think gets them moving.",
        "Update the planter description to mention the drainage hole.",
        "帮我写个商品标题",
        "销售额下周要冲一冲",  # 有业绩词但没有疑问线索词
    ],
)
def test_operational_turns_are_not_pinned(config, text):
    assert forced(config, text) is None


@pytest.mark.parametrize(
    ("setting", "text"),
    [("metrics_grounding_gate", "How were sales last week?")],
    # 项目中还有 queue_grounding_gate 一行，Step 20 再加
)
def test_each_rule_has_a_config_switch(config, setting, text):
    assert forced(config, text) is not None
    assert forced(config.model_copy(update={setting: False}), text) is None
