"""Step 15.5 最小可体验原型。

三个核心模式：
1. 会话管理 —— 内存 dict，POST /api/session 创建
2. SSE 流式输出 —— POST /api/chat 调用 stream_turn()，to_sse() 序列化
3. 按钮加购 —— POST /api/cart/add 走同一个 executor 和门控

启动：
    cd commerce-agents-dev
    uvicorn examples.prototype.app:app --reload --port 8000
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from commerce_common.skills import SkillRegistry
from commerce_common.streaming import AgentEvent, to_sse
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from shopping_agent import (
    ShoppingAgentConfig,
    ShoppingSessionContext,
    ShoppingSessionState,
    cart_payload,
)
from shopping_agent.executor import ShoppingToolExecutor
from shopping_agent.fencing import STOREFRONT_FENCE
from shopping_agent_runtime import ShoppingAgent

from .backend import DemoBackend

logger = logging.getLogger(__name__)

# ── 会话存储 ────────────────────────────────────────────────────
# 最简单的形式：一个 dict。Step 22 的 SessionStore 加上版本化和 CAS。


@dataclass
class Session:
    session_id: str
    context: ShoppingSessionContext
    state: ShoppingSessionState = field(default_factory=ShoppingSessionState)
    messages: list[dict[str, Any]] = field(default_factory=list)


sessions: dict[str, Session] = {}


def get_session(request: Request) -> Session:
    session_id = request.headers.get("x-session-id", "")
    s = sessions.get(session_id)
    if s is None:
        raise HTTPException(status_code=401, detail="Missing or invalid X-Session-Id")
    return s


# ── 请求体 ──────────────────────────────────────────────────────


class ChatRequest(BaseModel):
    message: str


class CartAddRequest(BaseModel):
    product_id: str
    quantity: int = 1


# ── 组装 ────────────────────────────────────────────────────────

SKILLS_DIR = (
    Path(__file__).resolve().parents[2] / "shopping-agent" / "core" / "shopping_agent" / "skills"
)

backend = DemoBackend()
skills = SkillRegistry.from_dir(SKILLS_DIR) if SKILLS_DIR.is_dir() else SkillRegistry([])
config = ShoppingAgentConfig(brand_name="ACME", assistant_name="Scout")
agent = ShoppingAgent(backend=backend, skills_dir=SKILLS_DIR, config=config)

app = FastAPI(title="Shopping Agent Prototype")
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 路由 ────────────────────────────────────────────────────────


@app.post("/api/session")
async def create_session():
    sid = secrets.token_urlsafe(16)
    ctx = ShoppingSessionContext(session_id=sid, user_id="demo-user")
    sessions[sid] = Session(session_id=sid, context=ctx)
    return {"session_id": sid}


@app.post("/api/chat")
async def chat(body: ChatRequest, request: Request):
    s = get_session(request)
    s.messages.append({"role": "user", "content": body.message})

    async def event_stream():
        try:
            async for event in agent.stream_turn(s.messages, s.context, s.state):
                yield to_sse(event)
        except Exception:
            logger.exception("stream_turn failed")
            yield to_sse(AgentEvent.error("Internal error, please try again."))

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/cart")
async def get_cart(request: Request):
    s = get_session(request)
    cart = await backend.get_cart(s.context)
    return cart_payload(cart)


@app.post("/api/cart/add")
async def add_to_cart(body: CartAddRequest, request: Request):
    # 按钮加购：实例化同一个 executor，走同一套门控
    s = get_session(request)
    executor = ShoppingToolExecutor(
        backend=backend,
        config=config,
        skills=skills,
        session=s.context,
        state=s.state,
    )
    outcome = await executor.execute(
        "add_to_cart", {"product_id": body.product_id, "quantity": body.quantity}
    )
    if outcome.blocked or outcome.is_error:
        raise HTTPException(status_code=400, detail=outcome.result_text.split(". ")[0] + ".")
    cart = next((e.data.get("cart") for e in outcome.events if e.type == "cart_update"), None)
    product = s.state.seen_products.get(body.product_id)
    title = STOREFRONT_FENCE.sanitize_text(product.title) if product else "item"
    logger.info("Button add: %s (%s) x%d", title, body.product_id, body.quantity)
    return {"ok": True, "cart": cart}


@app.get("/")
async def index():
    return FileResponse(Path(__file__).parent / "index.html")
