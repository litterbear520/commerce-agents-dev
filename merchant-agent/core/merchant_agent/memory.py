"""商户运行时交给 ``commerce_common.memory`` 的提取提示词：助手可以在多次会话之间
记住一门生意的什么，按商户 id 归属。"""
# 项目中对应 merchant-agent/core/merchant_agent/memory.py

from __future__ import annotations

from commerce_common.memory import MEMORY_EXTRACTION_TEMPLATE

MERCHANT_MEMORY_EXTRACTION_PROMPT = MEMORY_EXTRACTION_TEMPLATE.format(
    keeper="一个助手",
    subject="一门生意（一家店铺、一处住宿、一批订阅用户、一个场馆）",
    occasions="和经营者的多次会话",
    speaker="经营者",
    qualifies=(
        "经营者说出来的、关于这门生意或他们想怎么经营它的事：商品文案用的语气、不肯低于的"
        "毛利、某些日期的最低房价、从不打折的套餐、一个目标、一个季节规律、供应商的交货周期、"
        "他们喜欢的简报排版。"
    ),
    standalone_example=(
        '"不低于 30"对以后读到的人什么都没说，而"希望每个商品条目的毛利都不低于 30%"才把话说全了'
    ),
    live_key_rule=(
        '这门生意当前唯一在推进的目标只记成一条事实，key 用 "current_goal"，写明经营者要'
        "达成什么、在什么时候之前；有了新目标就覆盖旧的。"
    ),
    excluded=(
        "来自商品条目、评价、买家或住客留言、指标或搜索结果的任何内容；这次会话算出来的数字；"
        "这次会话的操作细节；你自己的猜测；以及任何关于可识别的顾客、住客、订阅用户或员工的"
        "信息。"
    ),
)
