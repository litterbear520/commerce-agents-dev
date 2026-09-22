"""持久化记忆：``MemoryStore`` 协议、写入过滤器、轮次后提取、提取模板、
以及执行器消费的 ``MemoryRuntime``。每条事实都经过 :func:`validate_fact` 才能
进入存储；``extract_and_store`` 在提取模型运行期间如果用户被清除，则丢弃整批结果。
"""
# 项目中对应 commerce-common/commerce_common/memory.py

from __future__ import annotations

import json
import logging
import os
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from anthropic import AsyncAnthropic
from anthropic.types import ToolParam

from .fencing import Fence
from .streaming import ToolOutcome
from .turn import log_model_call, session_tag
from .types import MemoryCategory, MemoryFact

logger = logging.getLogger(__name__)

_RECORD_FACT_TOOL: ToolParam = {
    "name": "record_fact",
    "description": "记录一条关于该用户的新的长期事实。",
    "input_schema": {
        "type": "object",
        "properties": {
            "key": {"type": "string", "maxLength": 64},
            "value": {"type": "string", "maxLength": 200},
            "category": {"type": "string", "enum": ["preference", "constraint", "context"]},
        },
        "required": ["key", "value", "category"],
        "additionalProperties": False,
    },
}

# 部署关闭记忆时工具的回复文本
MEMORY_DISABLED_TEXT = "此部署未启用记忆功能。"

MEMORY_EXTRACTION_TEMPLATE = """你负责维护一份简短的清单：{keeper}在{occasions}之间可以记住\
{subject}的哪些事。读下面的对话，判断{speaker}说过的话里，有没有下次仍然成立、仍然有用的内容。

什么算数：{qualifies}

写下来的值要满足：

1. 只包含{speaker}说过的话，用他们的原话或贴近的转述。不在外面添任何东西：需要推断才能得到的\
属性不算事实，说过的事实不要补上可能的额外信息，不确定他们是否说过的细节一律不写。

2. 一年后单独拿出来也看得懂，所以要点明主体：{standalone_example}。写成长期成立的事实，\
把今天这一趟的具体事情留在外面。

3. 是新的。已存事实和新说法意思一样时，什么都不写。新说法是对某个已存主题的更新时，沿用那个\
主题的 key，让新值覆盖旧值。{live_key_rule}

完全不写的：{excluded}

对话里没有任何符合条件的内容时，什么都不记。"""
"""提取系统提示词；每个角色在导入时渲染一次。"""


# ── MemoryStore 协议 ────────────────────────────────────────────────


class MemoryStore(Protocol):
    """对接你自己的存储。``subject_id`` 是事实所属的用户或商户。"""

    async def get_facts(self, subject_id: str) -> list[MemoryFact]: ...

    async def upsert_facts(self, subject_id: str, facts: list[MemoryFact]) -> None: ...

    async def search_facts(self, subject_id: str, query: str) -> list[MemoryFact]: ...

    async def delete_fact(self, subject_id: str, key: str) -> bool:
        """按 key 删除一条事实；删除成功返回 True。"""
        ...

    async def clear(self, subject_id: str) -> None:
        """清除该用户的所有事实并推进清除代数。"""
        ...

    async def purge_generation(self, subject_id: str) -> int:
        """该用户被清除了多少次；从未清除返回 0。"""
        ...


MEMORY_STORE_METHODS: tuple[str, ...] = tuple(
    name
    for name, member in vars(MemoryStore).items()
    if callable(member) and not name.startswith("_")
)


def check_memory_store(store: MemoryStore) -> MemoryStore:
    """如果 ``store`` 缺少 :class:`MemoryStore` 的某个方法则抛 ``TypeError``。
    在部署入口处运行，让不完整的 store 在启动时就报错，而不是在轮次后的
    提取阶段才失败（那里的失败不会中断轮次）。"""
    for name in MEMORY_STORE_METHODS:
        if not callable(getattr(store, name, None)):
            raise TypeError(
                f"{type(store).__name__} 没有实现 MemoryStore.{name}；store 契约是 "
                f"{', '.join(MEMORY_STORE_METHODS)}"
            )
    return store


# ── 写入过滤器 ──────────────────────────────────────────────────────


class MemoryWriteRejected(ValueError):
    """候选事实匹配了写入过滤器；消息不会携带该值。"""


DEFAULT_BLOCKED_PATTERNS: tuple[str, ...] = (
    # 9 位以上的数字（可选空格/横线/点/括号分隔），覆盖信用卡、账号、身份证号、电话。
    # 日期、价格和尺码更短，不会匹配。
    r"(?:\d[ .()-]{0,2}){8}\d",
    # IBAN 格式的账户标识。
    r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b",
    # 邮箱地址。
    r"[^\s@]+@[^\s@]+\.[A-Za-z]{2,}",
)

MEMORY_WRITE_REJECTED_TEXT = "未保存：记忆只存偏好和长期规则，不存账号、卡号或联系方式。"

MemoryWriteCheck = Callable[[str, str], bool]
"""``check(key, value)`` 返回 True 表示拒绝该事实；在正则之后运行。"""


@dataclass(frozen=True)
class MemoryWriteFilter:
    """候选事实的 key 或 value 不能包含的内容。用 :meth:`build` 构建；
    正则按原样搜索，把 flag 写在正则内联里。"""

    patterns: tuple[re.Pattern[str], ...]
    checks: tuple[MemoryWriteCheck, ...] = ()

    @classmethod
    def build(
        cls,
        extra_patterns: Iterable[str] = (),
        *,
        checks: Iterable[MemoryWriteCheck] = (),
        defaults: Iterable[str] = DEFAULT_BLOCKED_PATTERNS,
    ) -> MemoryWriteFilter:
        return cls(
            tuple(re.compile(pattern) for pattern in (*defaults, *extra_patterns)),
            tuple(checks),
        )

    def rejects(self, key: str, value: str) -> bool:
        if any(pattern.search(text) for text in (key, value) for pattern in self.patterns):
            return True
        return any(check(key, value) for check in self.checks)


@lru_cache(maxsize=32)
def write_filter_for(extra_patterns: tuple[str, ...] = ()) -> MemoryWriteFilter:
    """按配置的 ``memory_blocked_patterns`` 编译一次过滤器。"""
    return MemoryWriteFilter.build(extra_patterns)


def validate_fact(
    key: str,
    value: str,
    category: str | None = None,
    *,
    fence: Fence,
    write_filter: MemoryWriteFilter | None,
    source_session_id: str | None = None,
) -> MemoryFact:
    """标准化候选事实并通过写入过滤器。被拒绝时抛 :class:`MemoryWriteRejected`；
    ``write_filter=None`` 跳过过滤。``fence`` 是角色的围栏，它的标记会从每个字段
    中剥离。``source_session_id`` 原样存储；调用方传写入会话的 :func:`session_tag`
    而非 id（参见 :class:`MemoryFact`）。"""
    fact = MemoryFact(
        key=fence.sanitize_text(key, 64).strip().lower().replace(" ", "_"),
        value=fence.sanitize_text(value, 200).strip(),
        category=MemoryCategory(category) if category else MemoryCategory.PREFERENCE,
        updated_at=datetime.now(UTC),
        source_session_id=(
            fence.sanitize_text(source_session_id, 80) if source_session_id else None
        ),
    )
    if write_filter is not None and write_filter.rejects(fact.key, fact.value):
        raise MemoryWriteRejected(MEMORY_WRITE_REJECTED_TEXT)
    return fact


# ── 读取 ────────────────────────────────────────────────────────────


def match_facts(facts: list[MemoryFact], query: str) -> list[MemoryFact]:
    """参考的关键词匹配实现：查询词出现在 key、value 或 category 中即匹配。
    空查询匹配所有。"""
    terms = [term for term in query.lower().split() if term]
    if not terms:
        return list(facts)
    return [
        fact
        for fact in facts
        if any(term in f"{fact.key} {fact.value} {fact.category.value}".lower() for term in terms)
    ]


def select_tier_one_facts(facts: list[MemoryFact], cap: int = 8) -> list[MemoryFact]:
    """注入每次请求的事实：所有 constraint，再加上最近更新的事实，合计不超过 ``cap``。
    剩下的通过 ``recall_memories`` 工具可达。"""
    oldest = datetime.min.replace(tzinfo=UTC)

    def recency(fact: MemoryFact) -> datetime:
        # store 可能返回无时区的时间戳；按 UTC 比较，与 is_live 一致。
        updated = fact.updated_at or oldest
        return updated if updated.tzinfo else updated.replace(tzinfo=UTC)

    constraints = [fact for fact in facts if fact.category is MemoryCategory.CONSTRAINT]
    others = sorted(
        (fact for fact in facts if fact.category is not MemoryCategory.CONSTRAINT),
        key=recency,
        reverse=True,
    )
    return constraints + others[: max(0, cap - len(constraints))]


def memory_fact_payload(fact: MemoryFact) -> dict[str, str]:
    """每条事实交给模型时的形状，含溯源信息。"""
    payload = {"key": fact.key, "value": fact.value, "category": fact.category.value}
    if fact.source_session_id:
        payload["source_session"] = fact.source_session_id
    return payload


def render_memory_block(facts: list[MemoryFact]) -> str:
    if not facts:
        return "没有已保存的事实。"
    lines = []
    for fact in facts:
        provenance = f"（来自会话 {fact.source_session_id}）" if fact.source_session_id else ""
        lines.append(f"- {fact.key}: {fact.value} [{fact.category.value}]{provenance}")
    return "\n".join(lines)


# ── 存储实现 ─────────────────────────────────────────────────────────


class InMemoryMemoryStore:
    """临时存储，用于测试和单进程 demo。"""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, MemoryFact]] = {}
        self._purges: dict[str, int] = {}

    async def get_facts(self, subject_id: str) -> list[MemoryFact]:
        return list(self._data.get(subject_id, {}).values())

    async def upsert_facts(self, subject_id: str, facts: list[MemoryFact]) -> None:
        bucket = self._data.setdefault(subject_id, {})
        for fact in facts:
            bucket[fact.key] = fact

    async def search_facts(self, subject_id: str, query: str) -> list[MemoryFact]:
        return match_facts(await self.get_facts(subject_id), query)

    async def delete_fact(self, subject_id: str, key: str) -> bool:
        return self._data.get(subject_id, {}).pop(key, None) is not None

    async def clear(self, subject_id: str) -> None:
        self._data.pop(subject_id, None)
        self._purges[subject_id] = self._purges.get(subject_id, 0) + 1

    async def purge_generation(self, subject_id: str) -> int:
        return self._purges.get(subject_id, 0)


class JsonFileMemoryStore:
    """每个用户的事实存一个 JSON 文件，demo 不需要数据库。布局：
    ``{"version": 2, "facts": {subject: {key: fact}}, "purges": {subject: n}}``；
    清除计数存在文件里，这样一个 worker 里的清除操作在另一个 worker 的提取过程中可见。"""

    def __init__(self, path: Path):
        self._path = path

    def _read(self) -> tuple[dict[str, dict[str, dict[str, Any]]], dict[str, int]]:
        if not self._path.exists():
            return {}, {}
        data = json.loads(self._path.read_text(encoding="utf-8") or "{}")
        return dict(data.get("facts") or {}), dict(data.get("purges") or {})

    def _write(self, facts: dict[str, Any], purges: dict[str, int]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 2, "facts": facts, "purges": purges}
        content = json.dumps(payload, indent=2, default=str).encode("utf-8")
        # 文件存个人数据：只允许所有者读写。
        descriptor = os.open(self._path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(descriptor, content)
        finally:
            os.close(descriptor)

    async def get_facts(self, subject_id: str) -> list[MemoryFact]:
        facts, _ = self._read()
        return [MemoryFact.model_validate(raw) for raw in facts.get(subject_id, {}).values()]

    async def upsert_facts(self, subject_id: str, facts: list[MemoryFact]) -> None:
        stored, purges = self._read()
        bucket = stored.setdefault(subject_id, {})
        for fact in facts:
            bucket[fact.key] = fact.model_dump(mode="json")
        self._write(stored, purges)

    async def search_facts(self, subject_id: str, query: str) -> list[MemoryFact]:
        return match_facts(await self.get_facts(subject_id), query)

    async def delete_fact(self, subject_id: str, key: str) -> bool:
        stored, purges = self._read()
        bucket = stored.get(subject_id, {})
        if key not in bucket:
            return False
        bucket.pop(key)
        self._write(stored, purges)
        return True

    async def clear(self, subject_id: str) -> None:
        stored, purges = self._read()
        stored.pop(subject_id, None)
        purges[subject_id] = purges.get(subject_id, 0) + 1
        self._write(stored, purges)

    async def purge_generation(self, subject_id: str) -> int:
        _, purges = self._read()
        return purges.get(subject_id, 0)


class RetentionMemoryStore:
    """在任意 store 上加一层过期限制：``updated_at`` 超过 ``retention`` 的事实
    （或没有时间戳的）永远不返回，并在下次写入时删除。``clear`` 无视过期直接清除。"""

    def __init__(
        self,
        inner: MemoryStore,
        retention: timedelta,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if retention <= timedelta(0):
            raise ValueError("过期窗口必须为正")
        self.inner = inner
        self.retention = retention
        self._clock = clock

    def is_live(self, fact: MemoryFact) -> bool:
        if fact.updated_at is None:
            return False
        updated = fact.updated_at
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=UTC)
        return updated >= self._clock() - self.retention

    async def get_facts(self, subject_id: str) -> list[MemoryFact]:
        return [fact for fact in await self.inner.get_facts(subject_id) if self.is_live(fact)]

    async def search_facts(self, subject_id: str, query: str) -> list[MemoryFact]:
        facts = await self.inner.search_facts(subject_id, query)
        return [fact for fact in facts if self.is_live(fact)]

    async def upsert_facts(self, subject_id: str, facts: list[MemoryFact]) -> None:
        for expired in await self.inner.get_facts(subject_id):
            if not self.is_live(expired):
                await self.inner.delete_fact(subject_id, expired.key)
        await self.inner.upsert_facts(subject_id, facts)

    async def delete_fact(self, subject_id: str, key: str) -> bool:
        return await self.inner.delete_fact(subject_id, key)

    async def clear(self, subject_id: str) -> None:
        await self.inner.clear(subject_id)

    async def purge_generation(self, subject_id: str) -> int:
        return await self.inner.purge_generation(subject_id)


def with_retention(store: MemoryStore, retention_days: int | None) -> MemoryStore:
    """按配置包装 store：关闭过期时原样返回，否则包在 :class:`RetentionMemoryStore` 里。"""
    if retention_days is None:
        return store
    inner = store.inner if isinstance(store, RetentionMemoryStore) else store
    return RetentionMemoryStore(inner, timedelta(days=retention_days))


# ── 轮次后提取 ──────────────────────────────────────────────────────


def _normalize(value: str) -> str:
    return " ".join(value.lower().split())


def _same_fact(a: str, b: str) -> bool:
    """两个标准化后的值在一个包含另一个、或 Jaccard 重叠度 >= 0.6 时算同一条事实。"""
    if a in b or b in a:
        return True
    tokens_a = {token.strip(".,;:!?'\"()") for token in a.split()} - {""}
    tokens_b = {token.strip(".,;:!?'\"()") for token in b.split()} - {""}
    if not tokens_a or not tokens_b:
        return False
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b) >= 0.6


async def extract_facts(
    client: AsyncAnthropic,
    model: str,
    transcript: str,
    existing_facts: list[MemoryFact],
    max_new_facts: int = 3,
    *,
    extraction_prompt: str,
    fence: Fence,
    write_filter: MemoryWriteFilter | None,
    source_session_id: str | None = None,
) -> list[MemoryFact]:
    """让 ``model`` 从对话记录中提取新事实。被写入过滤器拒绝的、或与已有事实重复的
    提议会被丢弃；同一个 key 的提议是模板要求的更新，除非值不变否则保留。
    最多返回 ``max_new_facts`` 条。"""
    request: dict[str, Any] = {
        "model": model,
        "max_tokens": 600,
        "system": extraction_prompt,
        "tools": [_RECORD_FACT_TOOL],
        "messages": [
            {
                "role": "user",
                "content": (
                    f"已保存的事实：\n{render_memory_block(existing_facts)}\n\n"
                    f"对话记录：\n{fence.sanitize_text(transcript, 8000)}"
                ),
            }
        ],
    }
    started = time.monotonic()
    response = await client.messages.create(**request)
    log_model_call(logger, request, response, started, source_session_id, purpose="memory")
    held = {fact.key: _normalize(fact.value) for fact in existing_facts}
    known = set(held.values())
    facts: list[MemoryFact] = []
    for block in response.content:
        if block.type != "tool_use" or block.name != "record_fact" or len(facts) >= max_new_facts:
            continue
        data = block.input if isinstance(block.input, dict) else {}
        try:
            fact = validate_fact(
                str(data.get("key", "")),
                str(data.get("value", "")),
                str(data.get("category", "preference")),
                fence=fence,
                write_filter=write_filter,
                source_session_id=session_tag(source_session_id) if source_session_id else None,
            )
        except (ValueError, TypeError):  # 含 MemoryWriteRejected
            continue
        if not fact.key or not fact.value:
            continue
        value = _normalize(fact.value)
        current = held.get(fact.key)
        if current is not None:
            if value == current:
                continue
            known.discard(current)
        elif any(_same_fact(value, seen) for seen in known):
            continue
        held[fact.key] = value
        known.add(value)
        facts.append(fact)
    return facts


async def extract_and_store(
    store: MemoryStore,
    subject_id: str,
    client: AsyncAnthropic,
    model: str,
    transcript: str,
    *,
    extraction_prompt: str,
    fence: Fence,
    write_filter: MemoryWriteFilter | None,
    source_session_id: str | None = None,
) -> list[MemoryFact]:
    """对照 store 已有事实做提取并写入，除非在模型运行期间该用户的清除代数
    发生了变化。返回写入的事实。"""
    generation = await store.purge_generation(subject_id)
    existing = await store.get_facts(subject_id)
    new_facts = await extract_facts(
        client,
        model,
        transcript,
        existing,
        extraction_prompt=extraction_prompt,
        fence=fence,
        write_filter=write_filter,
        source_session_id=source_session_id,
    )
    if not new_facts or await store.purge_generation(subject_id) != generation:
        return []
    await store.upsert_facts(subject_id, new_facts)
    return new_facts


# ── 运行时 ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class MemoryRuntime:
    """一个部署的记忆，构建一次交给每个执行器：按配置包装的 store、写入过滤器、
    角色的围栏和提取模板。``enabled`` 关闭时不读写 store，记忆工具回复
    :data:`MEMORY_DISABLED_TEXT`；``store`` 对宿主代码始终可用。"""

    store: MemoryStore | None
    write_filter: MemoryWriteFilter
    fence: Fence
    extraction_prompt: str
    model: str
    tier_one_cap: int
    max_fenced_chars: int
    enabled: bool

    @classmethod
    def build(
        cls,
        config: Any,
        store: MemoryStore | None,
        *,
        fence: Fence,
        extraction_prompt: str,
        write_filter: MemoryWriteFilter | None = None,
    ) -> MemoryRuntime:
        """``config`` 是 ``BaseAgentConfig``。宿主提供的 ``write_filter``（携带自定义
        checks 的）替换从配置构建的那个。``store`` 缺少 :class:`MemoryStore` 方法时
        抛 ``TypeError``。"""
        if store is not None:
            store = with_retention(check_memory_store(store), config.memory_retention_days)
        return cls(
            store=store,
            write_filter=write_filter or write_filter_for(config.memory_blocked_patterns),
            fence=fence,
            extraction_prompt=extraction_prompt,
            model=config.memory_model,
            tier_one_cap=config.memory_tier_one_cap,
            max_fenced_chars=config.max_fenced_chars,
            enabled=bool(config.enable_memory and store is not None),
        )

    def validate(
        self, key: str, value: str, category: str | None, *, source_session_id: str | None
    ) -> MemoryFact:
        """:func:`validate_fact` 使用本部署的围栏和过滤器。"""
        return validate_fact(
            key,
            value,
            category,
            fence=self.fence,
            write_filter=self.write_filter,
            source_session_id=source_session_id,
        )

    async def tier_one(self, subject_id: str) -> list[MemoryFact]:
        """注入请求的事实；记忆关闭时返回空列表。"""
        if not self.enabled or self.store is None:
            return []
        return select_tier_one_facts(await self.store.get_facts(subject_id), self.tier_one_cap)

    async def save(
        self, subject_id: str, session_id: str, tool_input: dict[str, Any]
    ) -> ToolOutcome:
        """``save_memory`` 工具。"""
        if not self.enabled or self.store is None:
            return ToolOutcome(MEMORY_DISABLED_TEXT)
        try:
            fact = self.validate(
                str(tool_input.get("key", "")),
                str(tool_input.get("value", "")),
                str(tool_input.get("category", "preference")),
                source_session_id=session_tag(session_id),
            )
        except MemoryWriteRejected as rejected:
            return ToolOutcome.error(str(rejected))
        if not fact.key or not fact.value:
            return ToolOutcome.error("没有可保存的内容。")
        await self.store.upsert_facts(subject_id, [fact])
        return ToolOutcome(f"已保存：{fact.key}。")

    async def recall(self, subject_id: str, tool_input: dict[str, Any]) -> ToolOutcome:
        """``recall_memories`` 工具；匹配结果带围栏返回。"""
        if not self.enabled or self.store is None:
            return ToolOutcome(MEMORY_DISABLED_TEXT)
        topic = self.fence.sanitize_text(str(tool_input.get("topic", "")), 100)
        facts = await self.store.search_facts(subject_id, topic)
        payload = [memory_fact_payload(fact) for fact in facts]
        return ToolOutcome(
            self.fence.fence_payload(
                {"topic": topic, "facts": payload or "没有匹配的事实"}, self.max_fenced_chars
            )
        )

    async def extract(
        self, client: AsyncAnthropic, subject_id: str, session_id: str, transcript: str
    ) -> list[MemoryFact]:
        """轮次后的提取。记忆关闭、对话记录为空、或提取失败时返回空列表：
        记忆永远不会导致轮次失败，失败以 WARNING 级别记录并带堆栈。"""
        if not self.enabled or self.store is None or not transcript:
            return []
        try:
            return await extract_and_store(
                self.store,
                subject_id,
                client,
                self.model,
                transcript,
                extraction_prompt=self.extraction_prompt,
                fence=self.fence,
                write_filter=self.write_filter,
                source_session_id=session_id,
            )
        except Exception:
            logger.warning(
                "memory extraction failed for session %s; the turn continues without it",
                session_tag(session_id),
                exc_info=True,
            )
            return []
