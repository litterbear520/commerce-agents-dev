"""部署级别的购物 agent 配置；每次请求的值通过 ``ShoppingSessionContext`` 传入。"""
# 项目中对应 shopping-agent/core/shopping_agent/config.py
# 当前只包含身份、模型、购物车上限等基础字段
# 项目中 ShoppingAgentConfig 继承 commerce_common 的 BaseAgentConfig，
# Step 17 迁到 commerce_common 时再拆出基类

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ShoppingAgentConfig(BaseModel):
    # 所有可调参数集中在一个模型里，extra="forbid" 让拼写错误在构造时就报错

    model_config = ConfigDict(extra="forbid")

    # ── 身份（写入提示词）────────────────────────────────────────────
    brand_name: str = "ACME 商店"
    assistant_name: str = "购物助手"
    brand_voice: str = "热情、简洁，坦诚说明优缺点"

    # ── 模型 ────────────────────────────────────────────────────────
    model: str = "deepseek-v4-flash"
    max_tokens: int = 2048
    max_tool_iterations: int = 8

    # ── 购物车上限，由门控在所有路径上统一执行 ────────────────────────
    max_quantity_per_item: int = Field(default=24, ge=1)
    max_cart_lines: int = Field(default=100, ge=1)
