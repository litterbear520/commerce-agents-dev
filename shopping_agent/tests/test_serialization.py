# 项目中对应 shopping-agent/core/tests/test_serialization.py
# 当前不含 order_payload 测试（Step 13 补）

from shopping_agent import Cart, CartItem, Product, ProductDetails
from shopping_agent.serialization import (
    cart_payload,
    compact_product,
    product_details_payload,
)


def test_compact_product_carries_attributes():
    # attributes 保留在精简格式中
    product = Product(
        product_id="AR-0001",
        title="Trailhead Anorak",
        price=89.0,
        attributes={"color": "moss green", "fabric": "recycled ripstop"},
    )
    compact = compact_product(product)
    assert compact["attributes"] == {"color": "moss green", "fabric": "recycled ripstop"}


def test_compact_product_omits_empty_optionals():
    # 空字段不出现在精简格式中（省 token）
    compact = compact_product(Product(product_id="AR-0002", title="Camp Mug", price=9.0))
    for absent in (
        "attributes",
        "brand",
        "rating",
        "options",
        "option_values",
        "variant_of",
    ):
        assert absent not in compact


def test_family_details_carry_options_and_variant_rows():
    # 家族商品的详情带 options，变体只保留和家族不同的字段
    family = ProductDetails(
        product_id="AR-0003",
        title="Trail Pad",
        price=59.0,
        options={"length": ["regular", "long"]},
        variants=[
            Product(
                product_id="AR-0003-L",
                title="Trail Pad",
                price=69.0,
                option_values={"length": "long"},
                variant_of="AR-0003",
            )
        ],
    )
    payload = product_details_payload(family)
    assert payload["options"] == {"length": ["regular", "long"]}
    [variant] = payload["variants"]
    # 变体行：只保留 id、选项值、价格、库存（和家族相同的字段不重复）
    assert variant == {
        "product_id": "AR-0003-L",
        "option_values": {"length": "long"},
        "price": 69.0,
        "in_stock": True,
    }
    # 单独精简时，变体是完整记录，带 title 和 variant_of
    alone = compact_product(family.variants[0])
    assert alone["title"] == "Trail Pad" and alone["variant_of"] == "AR-0003"


def test_cart_lines_carry_option_keys_only_for_variants():
    # 普通商品的购物车行没有 option_values；变体的有
    plain = CartItem(product_id="AR-0002", title="Camp Mug", price=9.0, quantity=1)
    chosen = CartItem(
        product_id="AR-0003-L",
        title="Trail Pad",
        price=69.0,
        quantity=1,
        option_values={"length": "long"},
        variant_of="AR-0003",
    )
    lines = cart_payload(Cart(items=[plain, chosen]))["items"]
    assert "option_values" not in lines[0] and "variant_of" not in lines[0]
    assert lines[1]["option_values"] == {"length": "long"}
    assert lines[1]["variant_of"] == "AR-0003"


def test_cart_line_has_line_total():
    # 每行带计算好的 line_total（price × quantity）
    item = CartItem(product_id="p-1", title="东西", price=25.0, quantity=3)
    lines = cart_payload(Cart(items=[item]))["items"]
    assert lines[0]["line_total"] == 75.0
