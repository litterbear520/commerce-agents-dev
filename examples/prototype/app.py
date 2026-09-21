"""Step 15.5 最小可体验原型。

三个核心模式：
1. 会话管理 —— SessionStore + session_dependency，跟源码同结构
2. SSE 流式输出 —— POST /api/chat 调用 stream_turn()，to_sse() 序列化
3. 按钮加购 —— POST /api/cart/add 走同一个 executor 和门控

启动：
    cd commerce-agents-dev
    uvicorn examples.prototype.app:app --reload --port 8000

页面是 examples/retail/storefront-web，另外起在 3000 端口。
"""
# 项目中对应 examples/demo_common/sessions.py + storefront.py + host.py
# 原型把三个文件合在一起；Step 22 拆开

from __future__ import annotations

import logging
import secrets
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any

from commerce_common.skills import SkillRegistry
from commerce_common.streaming import AgentEvent, to_sse
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
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
from starlette.requests import HTTPConnection

from .backend import DemoBackend

logger = logging.getLogger(__name__)

SESSION_HEADER = "X-Session-Id"


# ── 会话存储 ────────────────────────────────────────────────────
# 项目中对应 examples/demo_common/sessions.py
# 源码的 SessionRecord 是泛型的（Generic[StateT]）；原型直接用 ShoppingSessionState。
# 源码的 SessionStore 把 state 和 transcript 分开存、CAS 版本校验；原型省略这些。


@dataclass
class SessionRecord:
    session_id: str
    user_id: str
    state: ShoppingSessionState = field(default_factory=ShoppingSessionState)
    messages: list[dict[str, Any]] = field(default_factory=list)


class SessionStore:
    def __init__(self) -> None:
        self._records: dict[str, SessionRecord] = {}

    def start(self, user_id: str) -> SessionRecord:
        record = SessionRecord(
            session_id=secrets.token_urlsafe(24),
            user_id=user_id,
        )
        self._records[record.session_id] = record
        return record

    def require(self, session_id: str) -> SessionRecord:
        record = self._records.get(session_id)
        if record is None:
            raise LookupError(session_id)
        return record


def session_dependency(store: SessionStore) -> Any:
    # 项目中对应 sessions.py 的 session_dependency()
    # yield 前加载会话，yield 后保存——原型的内存 dict 不需要显式保存，
    # 但保留 yield 结构，Step 22 加 CAS 写回时只需要在 yield 后面加 store.save()。
    def current_session(
        request: HTTPConnection,
    ) -> Iterator[SessionRecord]:
        session_id = request.headers.get(SESSION_HEADER)
        if not session_id:
            raise HTTPException(status_code=401, detail="先开一个会话（POST /api/session）")
        try:
            record = store.require(session_id)
        except LookupError as error:
            raise HTTPException(status_code=401, detail="会话不存在") from error
        yield record

    return Annotated[SessionRecord, Depends(current_session)]


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

sessions = SessionStore()
CurrentSession = session_dependency(sessions)

app = FastAPI(title="Shopping Agent Prototype")
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 路由 ────────────────────────────────────────────────────────
# 项目中对应 examples/demo_common/storefront.py + host.py


@app.post("/api/session")
async def create_session():
    record = sessions.start(user_id="demo-user")
    return {"session_id": record.session_id}


@app.post("/api/chat")
async def chat(body: ChatRequest, record: CurrentSession):
    record.messages.append({"role": "user", "content": body.message})
    ctx = ShoppingSessionContext(session_id=record.session_id, user_id=record.user_id)

    async def event_stream():
        try:
            async for event in agent.stream_turn(record.messages, ctx, record.state):
                yield to_sse(event)
        except Exception:
            logger.exception("stream_turn failed")
            yield to_sse(AgentEvent.error("服务出错了，请重试。"))

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/cart")
async def get_cart(record: CurrentSession):
    ctx = ShoppingSessionContext(session_id=record.session_id, user_id=record.user_id)
    cart = await backend.get_cart(ctx)
    return cart_payload(cart)


@app.post("/api/cart/add")
async def add_to_cart(body: CartAddRequest, record: CurrentSession):
    # 项目中对应 storefront.py 的 direct_add()
    # 按钮加购：实例化同一个 executor，走同一套门控
    ctx = ShoppingSessionContext(session_id=record.session_id, user_id=record.user_id)
    executor = ShoppingToolExecutor(
        backend=backend,
        config=config,
        skills=skills,
        session=ctx,
        state=record.state,
    )
    outcome = await executor.execute(
        "add_to_cart", {"product_id": body.product_id, "quantity": body.quantity}
    )
    if outcome.blocked or outcome.is_error:
        raise HTTPException(status_code=400, detail=outcome.result_text.split(". ")[0] + ".")
    cart = next((e.data.get("cart") for e in outcome.events if e.type == "cart_update"), None)
    product = record.state.seen_products.get(body.product_id)
    title = STOREFRONT_FENCE.sanitize_text(product.title) if product else "item"
    logger.info("Button add: %s (%s) x%d", title, body.product_id, body.quantity)
    return {"ok": True, "cart": cart}
