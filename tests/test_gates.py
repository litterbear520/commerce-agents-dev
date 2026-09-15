"""门控逻辑的单元测试。"""
# 后续步骤加的门控也往这里加

from s03_provenance_gate import (
    add_to_cart,
    cart,
    check_provenance,
    remember_products,
    seen_products,
    update_cart_item,
)
from s05_async import MAX_CART_LINES, MAX_QUANTITY_PER_ITEM
from s05_async import add_to_cart as s05_add_to_cart
from s05_async import cart as s05_cart
from s05_async import remember_products as s05_remember
from s05_async import seen_products as s05_seen
from s05_async import update_cart_item as s05_update
from s05_options_gate import VARIANTS, check_options
from s05_options_gate import seen_products as s05_sync_seen

# ── check_provenance ───────────────────────────────────────────────


def test_unseen_id_is_held():
    """没见过的 ID 被 provenance 门控拦截。"""
    result = check_provenance("XYZ-999")
    assert result is not None
    assert result.blocked == "provenance"


def test_seen_id_passes():
    """见过的 ID 放行（返回 None）。"""
    seen_products["AR-1105"] = {"id": "AR-1105", "title": "ACME Select 主动降噪耳机"}
    result = check_provenance("AR-1105")
    assert result is None


def test_held_text_contains_recovery_hint():
    """拦截结果的文本里包含恢复提示，告诉模型怎么做。"""
    result = check_provenance("XYZ-999")
    assert result is not None
    assert "get_product_details" in result.text
    assert "search_products" in result.text


# ── add_to_cart 门控 ───────────────────────────────────────────────


def test_add_to_cart_requires_provenance():
    """add_to_cart 对没见过的 ID 返回 held，不是 error。"""
    result = add_to_cart("XYZ-999")
    assert result.blocked == "provenance"
    assert len(cart) == 0


def test_add_to_cart_allows_seen_id():
    """add_to_cart 对见过的、有库存的 ID 正常执行。"""
    remember_products(
        [
            {
                "id": "AR-1104",
                "title": "ACME Select 矮轴机械键盘",
                "price": 99.0,
                "rating": 4.6,
                "in_stock": True,
                "description": "...",
            }
        ]
    )
    result = add_to_cart("AR-1104")
    assert result.blocked is None
    assert result.is_error is False
    assert len(cart) == 1
    assert cart[0]["product_id"] == "AR-1104"


def test_add_to_cart_rejects_out_of_stock():
    """add_to_cart 对见过但缺货的商品返回 error。"""
    remember_products(
        [
            {
                "id": "AR-1002",
                "title": "ACME Signature 15Bar 意式咖啡机（带蒸汽棒）",
                "price": 329.0,
                "rating": 4.7,
                "in_stock": False,
                "description": "...",
            }
        ]
    )
    result = add_to_cart("AR-1002")
    assert result.is_error is True
    assert "缺货" in result.text
    assert len(cart) == 0


# ── update_cart_item 门控 ──────────────────────────────────────────


def test_update_cart_item_requires_provenance():
    """update_cart_item 对没见过的 ID 同样被拦截。"""
    result = update_cart_item("XYZ-999", 3)
    assert result.blocked == "provenance"


# ── check_options（s05）────────────────────────────────────────────


def test_family_id_is_held():
    """family 商品（有 options）被选项门控拦截。"""
    s05_sync_seen["AR-2000"] = {
        "id": "AR-2000",
        "title": "ACME 基础款圆领T恤",
        "price": 79.0,
        "in_stock": True,
        "options": {"尺码": ["S", "M", "L"]},
    }
    result = check_options("AR-2000")
    assert result is not None
    assert result.blocked == "options"
    assert "尺码" in result.text


def test_variant_id_passes_options_check():
    """变体商品（没有 options）通过选项门控。"""
    s05_sync_seen["AR-2001"] = VARIANTS["AR-2001"]
    result = check_options("AR-2001")
    assert result is None


def test_plain_product_passes_options_check():
    """普通商品（没有 options）通过选项门控。"""
    s05_sync_seen["AR-1104"] = {
        "id": "AR-1104",
        "title": "键盘",
        "price": 99.0,
        "in_stock": True,
    }
    result = check_options("AR-1104")
    assert result is None


async def test_add_to_cart_blocks_family():
    """s05 的 add_to_cart 对 family 商品返回 held。"""
    s05_remember(
        [
            {
                "id": "AR-2000",
                "title": "ACME 基础款圆领T恤",
                "price": 79.0,
                "in_stock": True,
                "options": {"尺码": ["S", "M", "L"]},
            }
        ]
    )
    result = await s05_add_to_cart("AR-2000")
    assert result.blocked == "options"
    assert len(s05_cart) == 0


async def test_add_to_cart_allows_variant():
    """s05 的 add_to_cart 对变体商品正常执行。"""
    s05_remember([VARIANTS["AR-2002"]])
    result = await s05_add_to_cart("AR-2002")
    assert result.blocked is None
    assert result.is_error is False
    assert len(s05_cart) == 1
    assert s05_cart[0]["product_id"] == "AR-2002"


async def test_update_cart_blocks_family():
    """s05 的 update_cart_item 对 family 商品也拦截。"""
    s05_seen["AR-2000"] = {
        "id": "AR-2000",
        "title": "ACME 基础款圆领T恤",
        "price": 79.0,
        "in_stock": True,
        "options": {"尺码": ["S", "M", "L"]},
    }
    result = await s05_update("AR-2000", 2)
    assert result.blocked == "options"


# ── 数量上限（s05）────────────────────────────────────────────────

PLAIN_PRODUCT = {
    "id": "AR-1104",
    "title": "ACME Select 矮轴机械键盘",
    "price": 99.0,
    "in_stock": True,
}


async def test_add_to_cart_caps_quantity():
    """加购数量超过单品上限时，被截断到上限。"""
    s05_remember([PLAIN_PRODUCT])
    result = await s05_add_to_cart("AR-1104", quantity=30)
    assert result.blocked is None
    assert s05_cart[0]["quantity"] == MAX_QUANTITY_PER_ITEM  # 24，不是 30


async def test_add_to_cart_rejects_at_limit():
    """已有 24 件再加 → 直接拒绝。"""
    s05_remember([PLAIN_PRODUCT])
    s05_cart.append({"product_id": "AR-1104", "title": "键盘", "price": 99.0, "quantity": 24})
    result = await s05_add_to_cart("AR-1104", quantity=1)
    assert result.is_error is True
    assert "单品上限" in result.text


async def test_add_to_cart_rejects_cart_full():
    """购物车已满 100 行，新商品被拒绝。"""
    s05_remember([PLAIN_PRODUCT])
    for i in range(MAX_CART_LINES):
        s05_cart.append({"product_id": f"FAKE-{i}", "title": "x", "price": 1.0, "quantity": 1})
    result = await s05_add_to_cart("AR-1104")
    assert result.is_error is True
    assert "已满" in result.text


async def test_update_cart_caps_quantity():
    """update 数量超过单品上限时，被截断到上限。"""
    s05_remember([PLAIN_PRODUCT])
    s05_cart.append({"product_id": "AR-1104", "title": "键盘", "price": 99.0, "quantity": 5})
    result = await s05_update("AR-1104", quantity=50)
    assert result.is_error is False
    assert s05_cart[0]["quantity"] == MAX_QUANTITY_PER_ITEM  # 24，不是 50
