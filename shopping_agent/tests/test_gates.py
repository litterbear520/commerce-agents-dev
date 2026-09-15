# 门控逻辑的单元测试（包版本，直接测 gate 函数）
# Stage A 版本在 tests/test_gates.py
# test_executor.py 通过执行器间接测了同样的场景；这里测门控函数本身

from shopping_agent import Product, ShoppingSessionState
from shopping_agent.gates import (
    OPTIONS_GATE,
    PROVENANCE_GATE,
    check_options,
    check_provenance,
    provenance_error,
)

# ── check_provenance ───────────────────────────────────────────────


def test_unseen_id_is_held():
    # 没见过的 ID 被溯源门控拦截
    state = ShoppingSessionState()
    result = check_provenance(state, "XYZ-999")
    assert result is not None
    assert result.blocked == PROVENANCE_GATE


def test_seen_id_passes():
    # 见过的 ID 放行（返回 None）
    state = ShoppingSessionState()
    state.seen_products["p-100"] = Product(product_id="p-100", title="帐篷", price=149.0)
    result = check_provenance(state, "p-100")
    assert result is None


def test_held_text_contains_recovery_hint():
    # 拦截结果的文本包含恢复提示
    state = ShoppingSessionState()
    result = check_provenance(state, "XYZ-999")
    assert result is not None
    assert result.result_text == provenance_error("XYZ-999")
    assert "get_product_details" in result.result_text
    assert "搜索" in result.result_text


# ── check_options ──────────────────────────────────────────────────


def test_family_id_is_held():
    # 有 options 的家族商品被选项门控拦截
    state = ShoppingSessionState()
    state.seen_products["p-400"] = Product(
        product_id="p-400",
        title="Trail Sleeping Pad",
        price=59.0,
        options={"length": ["regular", "long"]},
    )
    result = check_options(state, "p-400")
    assert result is not None
    assert result.blocked == OPTIONS_GATE
    assert "length" in result.result_text


def test_variant_id_passes_options_check():
    # 变体商品（没有 options）通过选项门控
    state = ShoppingSessionState()
    state.seen_products["p-400-r"] = Product(
        product_id="p-400-r",
        title="Trail Sleeping Pad",
        price=59.0,
        option_values={"length": "regular"},
        variant_of="p-400",
    )
    result = check_options(state, "p-400-r")
    assert result is None


def test_plain_product_passes_options_check():
    # 普通商品（没有 options）通过选项门控
    state = ShoppingSessionState()
    state.seen_products["p-100"] = Product(product_id="p-100", title="帐篷", price=149.0)
    result = check_options(state, "p-100")
    assert result is None


def test_unseen_id_passes_options_check():
    # seen_products 里没有的 id，选项门控放行（溯源门控的事）
    state = ShoppingSessionState()
    result = check_options(state, "ghost")
    assert result is None
