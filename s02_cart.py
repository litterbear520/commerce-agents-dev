import json

# ── 假商品列表（来自 EVALS.md 的 6 个商品）──────────────────────────
PRODUCTS = [
    {
        "id": "AR-1104",
        "title": "ACME Select 矮轴机械键盘",
        "price": 99.0,
        "rating": 4.6,
        "in_stock": True,
        "description": "75% 紧凑布局，Gateron 矮轴红轴，铝合金框架，USB-C 有线连接。",
    },
    {
        "id": "AR-1105",
        "title": "ACME Select 主动降噪耳机",
        "price": 249.0,
        "rating": 4.8,
        "in_stock": True,
        "description": "混合主动降噪，40mm 驱动单元，蓝牙 5.3，续航 30 小时，可折叠设计。",
    },
    {
        "id": "AR-1106",
        "title": "ACME Select 1080p 自动取景摄像头",
        "price": 69.0,
        "rating": 4.3,
        "in_stock": True,
        "description": "1080p/30fps，AI 自动取景和人像居中，内置双麦克风，USB 即插即用。",
    },
    {
        "id": "AR-1107",
        "title": "ACME Studio 可调节铝合金笔记本支架",
        "price": 39.0,
        "rating": 4.5,
        "in_stock": True,
        "description": "6 档高度可调，铝合金材质，承重 8kg，适合 10-17 寸笔记本。",
    },
    {
        "id": "AR-1002",
        "title": "ACME Signature 15Bar 意式咖啡机（带蒸汽棒）",
        "price": 329.0,
        "rating": 4.7,
        "in_stock": False,
        "description": "15Bar 意式萃取，不锈钢蒸汽棒可打奶泡，58mm 无底手柄，2L 水箱。",
    },
    {
        "id": "AR-1008",
        "title": "ACME Rest 加重毯 Queen 尺寸",
        "price": 49.0,
        "rating": 4.4,
        "in_stock": True,
        "description": "Queen 尺寸 150×200cm，玻璃微珠填充，透气棉面料，可机洗。",
    },
]

# ── 购物车状态 ──────────────────────────────────────────────────────
# 项目中对应 types.py 的 CartItem / Cart
cart: list[dict] = []


# ── 工具 Schema ─────────────────────────────────────────────────────
# 字段名和描述与 shopping-agent/core/shopping_agent/tools/registry.py 一致

search_products_schema = {
    "name": "search_products",
    "description": (
        "搜索商品目录，返回商品的 id、标题、价格、评分和库存状态。"
        "用具体的关键词搜索。"
        "顾客提到多个不同商品时，每个商品单独搜一次。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "要搜索的关键词。",
            },
            "limit": {
                "type": "integer",
                "description": "最多返回几条结果。",
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    },
}

get_product_details_schema = {
    "name": "get_product_details",
    "description": (
        "查看一个商品的完整信息：描述、规格、评价摘要。"
        "用于回答关于某个商品的具体问题，或在加购前确认详情。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "product_id": {
                "type": "string",
                "description": "要查看的商品 product_id。",
            },
        },
        "required": ["product_id"],
        "additionalProperties": False,
    },
}

get_cart_schema = {
    "name": "get_cart",
    "description": "查看当前购物车内容，包含商品、数量和小计。",
    "input_schema": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
}

add_to_cart_schema = {
    "name": "add_to_cart",
    "description": (
        "把商品加入购物车，product_id 必须是本次会话中搜索或详情工具返回过的。"
        "数量默认为 1。如果商品缺货，告知顾客并推荐替代品。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "product_id": {
                "type": "string",
                "description": "本次会话中工具返回过的 product_id。",
            },
            "quantity": {
                "type": "integer",
                "minimum": 1,
                "description": "要添加的数量，省略则为 1。",
            },
        },
        "required": ["product_id"],
        "additionalProperties": False,
    },
}

update_cart_item_schema = {
    "name": "update_cart_item",
    "description": "修改购物车中已有商品的数量。",
    "input_schema": {
        "type": "object",
        "properties": {
            "product_id": {
                "type": "string",
                "description": "购物车中已有商品的 product_id。",
            },
            "quantity": {
                "type": "integer",
                "minimum": 1,
                "description": "新的数量。",
            },
        },
        "required": ["product_id", "quantity"],
        "additionalProperties": False,
    },
}

remove_from_cart_schema = {
    "name": "remove_from_cart",
    "description": "从购物车中移除一个商品。",
    "input_schema": {
        "type": "object",
        "properties": {
            "product_id": {
                "type": "string",
                "description": "要移除的商品的 product_id。",
            },
        },
        "required": ["product_id"],
        "additionalProperties": False,
    },
}

tools = [
    search_products_schema,
    get_product_details_schema,
    get_cart_schema,
    add_to_cart_schema,
    update_cart_item_schema,
    remove_from_cart_schema,
]


# ── 工具函数 ────────────────────────────────────────────────────────


def search_products(query: str, limit: int = 5) -> str:
    """在假商品列表里做简单的关键词匹配，返回 JSON 字符串。"""
    query_lower = query.lower()
    results = [p for p in PRODUCTS if query_lower in p["title"].lower()]
    results = results[:limit]
    return json.dumps(results, ensure_ascii=False)


def get_product_details(product_id: str) -> str:
    """按 product_id 查找商品，返回完整信息。"""
    for p in PRODUCTS:
        if p["id"] == product_id:
            return json.dumps(p, ensure_ascii=False)
    return json.dumps({"error": f"没有找到商品 {product_id}"}, ensure_ascii=False)


def get_cart() -> str:
    """返回当前购物车内容和小计。"""
    subtotal = sum(item["price"] * item["quantity"] for item in cart)
    return json.dumps({"items": cart, "subtotal": subtotal}, ensure_ascii=False)


def add_to_cart(product_id: str, quantity: int = 1) -> str:
    """把商品加入购物车。如果缺货则拒绝。"""
    product = next((p for p in PRODUCTS if p["id"] == product_id), None)
    if product is None:
        return json.dumps({"error": f"商品 {product_id} 不存在"}, ensure_ascii=False)
    if not product["in_stock"]:
        return json.dumps({"error": f"商品 {product['title']} 目前缺货"}, ensure_ascii=False)
    # 如果购物车里已有，增加数量
    for item in cart:
        if item["product_id"] == product_id:
            item["quantity"] += quantity
            return json.dumps(
                {
                    "ok": True,
                    "product_id": product_id,
                    "title": product["title"],
                    "quantity": item["quantity"],
                },
                ensure_ascii=False,
            )
    # 新增一行
    cart.append(
        {
            "product_id": product_id,
            "title": product["title"],
            "price": product["price"],
            "quantity": quantity,
        }
    )
    return json.dumps(
        {"ok": True, "product_id": product_id, "title": product["title"], "quantity": quantity},
        ensure_ascii=False,
    )


def update_cart_item(product_id: str, quantity: int) -> str:
    """修改购物车中已有商品的数量。"""
    for item in cart:
        if item["product_id"] == product_id:
            item["quantity"] = quantity
            return json.dumps(
                {"ok": True, "product_id": product_id, "quantity": quantity}, ensure_ascii=False
            )
    return json.dumps({"error": f"购物车中没有商品 {product_id}"}, ensure_ascii=False)


def remove_from_cart(product_id: str) -> str:
    """从购物车中移除商品。"""
    for i, item in enumerate(cart):
        if item["product_id"] == product_id:
            removed = cart.pop(i)
            return json.dumps({"ok": True, "removed": removed["title"]}, ensure_ascii=False)
    return json.dumps({"error": f"购物车中没有商品 {product_id}"}, ensure_ascii=False)


# ── 工具调用分发 ────────────────────────────────────────────────────
TOOL_MAP = {
    "search_products": search_products,
    "get_product_details": get_product_details,
    "get_cart": get_cart,  # get
    "add_to_cart": add_to_cart,  # post
    "update_cart_item": update_cart_item,  # put
    "remove_from_cart": remove_from_cart,  # delete
}


# ── 对话循环 ────────────────────────────────────────────────────────
if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    from anthropic import Anthropic

    client = Anthropic(base_url="https://api.deepseek.com/anthropic")
    model = "deepseek-v4-flash"
    system = "你是一个 ACME 购物助手。"
    messages: list = []

    while True:
        user_input = input(">>")
        if not user_input:
            break
        messages.append({"role": "user", "content": user_input})

        while True:
            response = client.messages.create(
                model=model,
                system=system,
                max_tokens=1000,
                tools=tools,  # type: ignore[list-item]
                messages=messages,
            )
            messages.append({"role": "assistant", "content": response.content})

            for block in response.content:
                if block.type == "text":
                    print(f"AI: {block.text}")

            if response.stop_reason != "tool_use":
                break

            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    print(f"[调用工具] {block.name}({block.input})")
                    run = TOOL_MAP[block.name]
                    output = run(**block.input)  # type: ignore[arg-type]
                    print(f"[工具结果] {output}")
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": output,
                        }
                    )
            messages.append({"role": "user", "content": tool_results})
