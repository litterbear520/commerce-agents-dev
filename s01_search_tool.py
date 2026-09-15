import json

# ── 假商品列表（来自 EVALS.md 的 6 个商品）──────────────────────────
PRODUCTS = [
    {
        "id": "AR-1104",
        "title": "ACME Select 矮轴机械键盘",
        "price": 99.0,
        "rating": 4.6,
        "in_stock": True,
    },
    {
        "id": "AR-1105",
        "title": "ACME Select 主动降噪耳机",
        "price": 249.0,
        "rating": 4.8,
        "in_stock": True,
    },
    {
        "id": "AR-1106",
        "title": "ACME Select 1080p 自动取景摄像头",
        "price": 69.0,
        "rating": 4.3,
        "in_stock": True,
    },
    {
        "id": "AR-1107",
        "title": "ACME Studio 可调节铝合金笔记本支架",
        "price": 39.0,
        "rating": 4.5,
        "in_stock": True,
    },
    {
        "id": "AR-1002",
        "title": "ACME Signature 15Bar 意式咖啡机（带蒸汽棒）",
        "price": 329.0,
        "rating": 4.7,
        "in_stock": False,
    },
    {
        "id": "AR-1008",
        "title": "ACME Rest 加重毯 Queen 尺寸",
        "price": 49.0,
        "rating": 4.4,
        "in_stock": True,
    },
]

# ── 工具 Schema ─────────────────────────────────────────────────────
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


# ── 搜索函数 ────────────────────────────────────────────────────────
def search_products(query: str, limit: int = 5) -> str:
    """在假商品列表里做简单的关键词匹配，返回 JSON 字符串。"""
    query_lower = query.lower()
    results = [p for p in PRODUCTS if query_lower in p["title"].lower()]
    results = results[:limit]
    return json.dumps(results, ensure_ascii=False)


# ── 工具调用分发 ────────────────────────────────────────────────────
TOOL_MAP = {
    "search_products": search_products,
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
                tools=[search_products_schema],  # type: ignore[list-item]
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
