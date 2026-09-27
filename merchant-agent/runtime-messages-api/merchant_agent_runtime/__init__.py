"""商户 agent 在 Messages API 上的实现：``MerchantAgent`` 跑轮次循环。"""
# 项目中对应 merchant-agent/runtime-messages-api/merchant_agent_runtime/__init__.py
# 省略：analysis 模块（run_analysis 背后的分析委托，Step 21）

from .orchestrator import MerchantAgent

__all__ = ["MerchantAgent"]
