# Step 15.5 最小可体验原型：一个文件装下会话存储、调用方和店面路由。
# 项目中对应 examples/demo_common/sessions.py + host.py + storefront.py，
# 加上 examples/retail/api/main.py 的组装；Step 22 拆开。
#
# 三个核心模式：
# 1. 会话管理 —— SessionStore + session_dependency
# 2. SSE 流式输出 —— POST /api/chat 调用 stream_turn()，to_sse() 序列化
# 3. 按钮加购 —— POST /api/cart/add 走同一个 executor 和门控（direct_add）
#
# 启动：uvicorn examples.prototype.app:app --reload --port 8000
# 页面是 examples/retail/storefront-web，另外起在 3000 端口。

# 下面的路由参数用运行时构建的依赖做注解，所以这个模块立即求值注解
# （不加 ``from __future__ import annotations``）。

import copy
import logging
import os
import secrets
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any

import anthropic
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from commerce_common.streaming import AgentEvent, to_sse
from shopping_agent import ShoppingAgentConfig, ShoppingSessionContext, ShoppingSessionState
from shopping_agent.gates import OPTIONS_GATE, PROVENANCE_GATE
from shopping_agent.serialization import cart_payload as serialize_cart
from shopping_agent_runtime import ShoppingAgent

from .backend import FakeBackend

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]

# ── 会话 ──────────────────────────────────────────────────────────
# 项目中对应 examples/demo_common/sessions.py

SESSION_HEADER = "X-Session-Id"


class UnknownSessionError(LookupError):
    """没有这个 id 的活跃会话。"""


class SessionConflictError(RuntimeError):
    """另一个请求先写了这个会话；调用方重新加载后重试。"""


# 源码的 SessionRecord 和 SessionStore 是泛型的（Generic[StateT]），两个角色共用；
# 原型只有购物侧，直接写 ShoppingSessionState。
@dataclass
class SessionRecord:
    session_id: str
    user_id: str
    state: ShoppingSessionState
    messages: list[dict[str, Any]] = field(default_factory=list)
    # 存储里已有的内容，这样 ``save`` 只写差异：state 文档加载时的版本和内容，
    # 以及 ``messages`` 里已经存了多少条。
    version: int = 0
    stored_state: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)
    stored_messages: int = field(default=0, repr=False, compare=False)

    def state_document(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "state": self.state.model_dump(mode="json"),
        }


class SessionStore:
    def __init__(self, state_type: type[ShoppingSessionState]) -> None:
        self._state_type = state_type
        self._states: dict[str, tuple[int, dict[str, Any]]] = {}
        self._transcripts: dict[str, list[dict[str, Any]]] = {}

    def start(self, user_id: str) -> SessionRecord:
        record = SessionRecord(
            session_id=secrets.token_urlsafe(24), user_id=user_id, state=self._state_type()
        )
        self.save(record)
        return record

    def require(self, session_id: str) -> SessionRecord:
        stored = self.read_state(session_id)
        if stored is None:
            raise UnknownSessionError(session_id)
        version, document = stored
        messages = self.read_messages(session_id)
        return SessionRecord(
            session_id=session_id,
            user_id=document["user_id"],
            state=self._state_type.model_validate(document["state"]),
            messages=messages,
            version=version,
            stored_state=document,
            stored_messages=len(messages),
        )

    def save(self, record: SessionRecord) -> None:
        """先写 state 文档，带版本校验，只在它变了或对话记录变长时写，这样
        输掉竞争的请求什么都不会写入；然后写存储里还没有的那些消息。"""
        document = record.state_document()
        grew = record.stored_messages < len(record.messages)
        if document != record.stored_state or grew:
            self.write_state(record.session_id, document, record.version)
            record.version += 1
            record.stored_state = document
        if grew:
            new = record.messages[record.stored_messages :]
            self.write_messages(record.session_id, new, record.stored_messages)
            record.stored_messages = len(record.messages)

    # ── 存储：部署方放在自己的存储上实现的方法（源码六个，原型四个）──

    def read_state(self, session_id: str) -> tuple[int, dict[str, Any]] | None:
        return self._states.get(session_id)

    def write_state(self, session_id: str, document: dict[str, Any], version: int) -> None:
        """当存储里的版本还是 ``version``（会话刚开始时是 0）时，把 ``document``
        存为 ``version + 1``：共享存储里的比较并交换。"""
        current = self._states.get(session_id)
        if (current[0] if current else 0) != version:
            raise SessionConflictError(session_id)
        self._states[session_id] = (version + 1, document)

    # 两个方向都拷贝，跟真实存储一样：记录之后的修改只能通过 save 进入存储。
    def read_messages(self, session_id: str) -> list[dict[str, Any]]:
        return copy.deepcopy(self._transcripts.get(session_id, []))

    def write_messages(self, session_id: str, messages: list[dict[str, Any]], start: int) -> None:
        """从 ``start`` 起替换对话记录：``start`` 等于已存长度时是追加，
        轮次压缩过历史后则是整份重写。"""
        self._transcripts.setdefault(session_id, [])[start:] = copy.deepcopy(messages)


def session_dependency(store: SessionStore, start_route: str) -> Any:
    """一个角色的每条受限路由都声明的参数注解：请求头里的会话 id，解析成它的
    记录，并在响应发出前写回（FastAPI 的 function 作用域；流式轮次在流结束时
    再写回一次）。``start_route`` 是 401 详情里提到的登录路由；被另一个请求
    抢先的写入返回 409。"""

    def current_session(
        session_id: Annotated[str | None, Header(alias=SESSION_HEADER)] = None,
    ) -> Iterator[SessionRecord]:
        if not session_id:
            raise HTTPException(status_code=401, detail=f"先开一个会话（POST {start_route}）")
        try:
            record = store.require(session_id)
        except UnknownSessionError as error:
            raise HTTPException(status_code=401, detail="会话不存在") from error
        yield record
        try:
            store.save(record)
        except SessionConflictError as error:
            raise HTTPException(status_code=409, detail="会话已变化，请重试") from error

    return Annotated[SessionRecord, Depends(current_session, scope="function")]


# ── 调用方 ────────────────────────────────────────────────────────
# 项目中对应 examples/demo_common/host.py


def load_demo_env(example_root: Path) -> None:
    """在构造任何 agent 之前加载凭据和 API 地址。环境里已有的变量优先；示例
    自己的 ``.env`` 补上其余的，然后是仓库根目录的那份。空白的
    ``ANTHROPIC_BASE_URL``（``.env.example`` 的占位）会被去掉，客户端保持默认地址。"""
    load_dotenv(example_root / ".env", override=False)
    load_dotenv(REPO_ROOT / ".env", override=False)
    if not os.environ.get("ANTHROPIC_BASE_URL", "").strip():
        os.environ.pop("ANTHROPIC_BASE_URL", None)


def build_app(title: str) -> FastAPI:
    """一个只接受本地源的 FastAPI 应用。日志按 ``DEMO_LOG_LEVEL`` 写到 stderr：
    ``INFO`` 是每次模型调用一行，``DEBUG`` 加上请求和响应体。"""
    logging.basicConfig(
        level=os.environ.get("DEMO_LOG_LEVEL", "INFO").upper(),
        format="%(levelname)s %(name)s: %(message)s",
    )
    # 模型调用那一行日志已经包含 httpx 为同一个请求打的内容。
    logging.getLogger("httpx").setLevel(logging.WARNING)
    app = FastAPI(title=title, version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
        allow_methods=["*"],
        allow_headers=["*"],
    )
    return app


def stream_turn(
    agent: ShoppingAgent,
    sessions: SessionStore,
    record: SessionRecord,
    session: ShoppingSessionContext,
) -> StreamingResponse:
    """把一轮对话作为 SSE 流出；流结束后把记录写回（请求依赖在流开始前已经
    写回过一次）。异常记进日志，并以通用的错误事件报告给客户端。"""

    async def event_stream() -> AsyncIterator[str]:
        try:
            async for event in agent.stream_turn(record.messages, session, record.state):
                yield to_sse(event)
        except anthropic.AuthenticationError:
            logger.exception("对话轮次失败：API 认证")
            yield to_sse(
                AgentEvent.error(
                    "Anthropic API 认证失败（401）。请检查 examples/.env 或仓库根目录 "
                    ".env 中的 ANTHROPIC_API_KEY，清除 shell 中过期的导出变量，"
                    "或设置 ANTHROPIC_BASE_URL 指向你的 API 端点。"
                )
            )
        except Exception as error:  # 客户端拿到一个安全的事件，其余的进日志
            logger.exception("对话轮次失败")
            described = str(error).lower()
            if any(word in described for word in ("authentication", "credential", "api_key")):
                yield to_sse(
                    AgentEvent.error(
                        "没有配置 API 凭证，对话无法运行。请在 examples/.env 或仓库根目录 "
                        ".env 中设置 ANTHROPIC_API_KEY 并重启；除对话外的功能不需要密钥。"
                    )
                )
            else:
                yield to_sse(AgentEvent.error("我们这边出了点问题，请重试。"))

    def write_back() -> None:
        sessions.save(record)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        background=BackgroundTask(write_back),
    )


# ── 店面 ──────────────────────────────────────────────────────────
# 项目中对应 examples/demo_common/storefront.py

# 购物车门控拦下写入时，加购按钮收到的提示。
_HELD_ADD_TEXT = {
    PROVENANCE_GATE: "这个商品不在本次会话的结果里",
    OPTIONS_GATE: "加入前先和助手一起选好商品的规格",
}


class StartSessionRequest(BaseModel):
    # 示例里用来代替凭据的东西：一个用户 id。
    user_id: str = Field(default="demo-user", min_length=1, max_length=64)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class CartAddRequest(BaseModel):
    product_id: str = Field(min_length=1, max_length=80)
    quantity: int = Field(default=1, ge=1)


def context(record: SessionRecord) -> ShoppingSessionContext:
    """agent 看到的一次请求：身份来自记录。"""
    return ShoppingSessionContext(session_id=record.session_id, user_id=record.user_id)


async def cart_payload(record: SessionRecord) -> dict[str, Any]:
    cart = await backend.get_cart(context(record))
    return serialize_cart(cart)


async def direct_add(record: SessionRecord, request: CartAddRequest) -> dict[str, Any]:
    """UI 按钮的加购，和 agent 的 ``add_to_cart`` 走同一个执行器，所以来源校验
    和数量上限都生效。"""
    executor = agent.executor_class(
        backend=backend,
        config=agent.config,
        skills=agent.skills,
        session=context(record),
        state=record.state,
    )
    execution = await executor.execute(
        "add_to_cart", {"product_id": request.product_id, "quantity": request.quantity}
    )
    if execution.blocked or execution.is_error:
        # 结果文本是写给模型看的；按钮只拿第一句，或者门控的简短原因。
        detail = _HELD_ADD_TEXT.get(execution.blocked or "", execution.result_text)
        raise HTTPException(status_code=400, detail=detail.split("。")[0] + "。")
    product = record.state.seen_products.get(request.product_id)
    if product is None:
        raise HTTPException(status_code=400, detail="这个商品不在本次会话的结果里")
    # 源码在这里把按钮加购记进 record.pending_app_events，下一轮告诉模型；Step 22 补
    cart = next((e.data.get("cart") for e in execution.events if e.type == "cart_update"), None)
    return {"ok": True, "cart": cart}


# ── 组装 ──────────────────────────────────────────────────────────
# 项目中对应 examples/retail/api/main.py

load_demo_env(REPO_ROOT / "examples")

backend = FakeBackend()
agent = ShoppingAgent(
    backend=backend,
    skills_dir=REPO_ROOT / "shopping-agent" / "skills",
    config=ShoppingAgentConfig(brand_name="ACME", assistant_name="ACME Assistant"),
)

sessions: SessionStore = SessionStore(ShoppingSessionState)
# 垂直行业自己的路由用的参数注解：``record: CurrentSession``。
CurrentSession = session_dependency(sessions, "/api/session")
app = build_app("ACME Retail demo API")


@app.post("/api/session")
async def start_session(request: StartSessionRequest | None = None) -> dict:
    record = sessions.start((request or StartSessionRequest()).user_id)
    return {"session_id": record.session_id, "user_id": record.user_id}


@app.post("/api/chat")
async def chat(request: ChatRequest, record: CurrentSession) -> StreamingResponse:
    # 源码这里是 append_user_turn()：没有待告知的应用事件时，就是这一句
    record.messages.append({"role": "user", "content": request.message})
    return stream_turn(agent, sessions, record, context(record))


@app.get("/api/cart")
async def get_cart(record: CurrentSession) -> dict:
    return await cart_payload(record)


@app.post("/api/cart/add")
async def cart_add(request: CartAddRequest, record: CurrentSession) -> dict:
    return await direct_add(record, request)
