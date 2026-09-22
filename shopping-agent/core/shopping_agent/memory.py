"""购物运行时交给 ``commerce_common.memory`` 的提取提示词：
店铺可以在顾客的多次到访之间记住什么。"""
# 项目中对应 shopping-agent/core/shopping_agent/memory.py

from __future__ import annotations

from commerce_common.memory import MEMORY_EXTRACTION_TEMPLATE

SHOPPING_MEMORY_EXTRACTION_PROMPT = MEMORY_EXTRACTION_TEMPLATE.format(
    keeper="一家店铺或服务商",
    subject="一位顾客",
    occasions="多次到访",
    speaker="顾客",
    qualifies=(
        "顾客自己说出来的偏好、限制或长期背景：他们要的座位或房型、尺码、家里几条线路每月的"
        "花费上限、通常和谁一起出行、避开的材质、反复回购的品牌。"
    ),
    standalone_example=(
        '"每月 90 以内"对以后读到的人什么都没说，而"希望家里三条线路每月合计控制在 90 以内"'
        "才把话说全了"
    ),
    live_key_rule=(
        "顾客手上正在进行的那一件事（一次出行、一个房间、一场活动）只记成一条事实，key 用 "
        '"current_project"，写明是什么场合、为谁、预算多少；有了新的一件就覆盖旧的。'
    ),
    excluded=(
        "来自商品列表、搜索结果或店铺条款的任何内容；这次到访的操作细节（搜了什么、往购物车里"
        "放了什么）；你自己的猜测；以及健康、财务、身份相关的信息——除非顾客明确要求记下来。"
    ),
)
