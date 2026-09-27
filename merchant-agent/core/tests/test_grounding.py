"""商户场景的数据锚定规则测试：默认词汇表下哪些消息强制读取经营快照。"""
# 项目中对应 merchant-agent/core/tests/test_grounding.py
# 省略：审批队列规则、跟进提醒检测 change_requested 的用例（Step 20）

import pytest

from commerce_common.grounding import first_forced_tool
from merchant_agent import MerchantSessionState
from merchant_agent.grounding import GROUNDING_RULES


def forced(config, text: str, state: MerchantSessionState | None = None) -> str | None:
    return first_forced_tool(GROUNDING_RULES, config, text, state or MerchantSessionState())


@pytest.mark.parametrize(
    "text",
    [
        "How were sales last week?",
        "What's the conversion trend?",
        "上周卖得怎么样？",
        "这个月的转化率为什么下滑了",
        "对比一下本周和上周的订单",
    ],
)
def test_performance_questions_force_the_snapshot(config, text):
    assert forced(config, text) == "get_business_snapshot"


@pytest.mark.parametrize(
    "text",
    [
        "Anything urgent this morning?",
        "Update the planter description to mention the drainage hole.",
        "帮我写个商品标题",
        "销售额下周要冲一冲",  # 有业绩词，没有疑问线索
    ],
)
def test_operational_turns_are_not_pinned(config, text):
    assert forced(config, text) is None


def test_the_metrics_rule_has_a_config_switch(config):
    text = "How were sales last week?"
    assert forced(config, text) is not None
    assert forced(config.model_copy(update={"metrics_grounding_gate": False}), text) is None
