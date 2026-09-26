# 项目中对应 merchant-agent/core/tests/test_prompt.py
# 省略：网页搜索开关（enable_web_search 未加）、暂存工具的条目上限（Step 20）

from datetime import datetime

from commerce_common.types import MemoryCategory, MemoryFact
from merchant_agent.fencing import MERCHANT_FENCE
from merchant_agent.prompt import build_dynamic_context, build_static_system


def test_static_system_mentions_store_skills_and_fence(config, skills):
    text = build_static_system(config, skills)
    assert "ACME" in text
    assert "performance-insights" in text
    assert "merchant_data" in text  # 围栏说明在里面
    # 项目中还断言 apply_change 出现（审批规则），Step 20 再加
    assert "商户助手" in text  # 没有编造的人设


def test_dynamic_context_is_fenced_and_contains_store_data():
    block = build_dynamic_context(
        merchant_context={
            "store": "ACME",
            "current_period": "2026-06-19/2026-06-25",
            "alerts": {"low_stock": 2, "order_issues": 1},
            "operator": "demo-operator",
        },
        memory_facts=[
            MemoryFact(
                key="margin_floor",
                value="利润率保持在 30% 以上",
                category=MemoryCategory.CONSTRAINT,
            ),
        ],
        now=datetime(2026, 6, 26, 9, 41),
    )
    assert block.startswith("# 商户上下文")
    assert MERCHANT_FENCE.open in block and MERCHANT_FENCE.close in block
    assert "<storefront_data>" not in block
    assert "current_period" in block
    assert "margin_floor" in block
    assert "2026-06-26T09:00" in block
    without_clock = build_dynamic_context(merchant_context=None, memory_facts=[], now=None)
    assert "local_time" not in without_clock


def test_dynamic_context_oversize_store_context_collapses_to_note():
    block = build_dynamic_context(
        merchant_context={"history": "x" * 5000},
        memory_facts=[],
        merchant_context_max_chars=2000,
    )
    # 围栏会做 NFKC 规范化，全角逗号进块后变成半角，所以只比对逗号前的部分
    assert "商户上下文太大" in block
    assert "xxxx" not in block


def test_dynamic_context_without_store_context_has_no_store_key():
    block = build_dynamic_context(merchant_context=None, memory_facts=[])
    assert '"store"' not in block
    assert '"saved_memory"' in block
