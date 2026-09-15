from __future__ import annotations

import threading
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

Route = Literal["direct", "tools", "memory", "speak"]


class TurnScores(TypedDict, total=False):
    spoken_quality: float
    grounding: float
    instruction_follow: float
    leak_risk: float
    overall: float
    prompt_version: int


class TurnState(TypedDict, total=False):
    user_text: str
    memory_block: str
    route: Route
    route_kind: str
    tool_results: list[tuple[str, str]]
    draft: str
    spoken: str
    chunks: list[str]
    scores: TurnScores
    used_tools: bool
    gate_ok: bool
    trusted_reply: bool
    judge_ok: bool
    judge_reason: str
    used_fallback: bool
    repair_count: int
    prompt_version: int
    session_id: int


@dataclass
class TurnRuntime:
    """Per-turn handles that must not live in graph state (Events, callbacks)."""

    llm: Any
    on_tool: Callable[[str, Any], str] | None = None
    on_thought: Callable[[str], None] | None = None
    cancel: threading.Event | None = None
    tools: list[dict[str, Any]] | None = None
    max_rounds: int = 4
    memory: Any = None
    session_memory: Any = None
    session_id: int | None = None
    settings: Any = None
    registry: Any = None
    chat_store: Any = None
    tool_timeout_sec: float = 20.0
    memory_max_inject: int = 8
    session_rag_max_inject: int = 6
    session_rag_enabled: bool = True
    tools_enabled: bool = True
    validator_on_tools: bool = True
    score_sample_rate: float = 0.15
    on_status: Callable[[str], None] | None = None
    extra: dict[str, Any] = field(default_factory=dict)


_RUNTIME: ContextVar[TurnRuntime | None] = ContextVar("bob_turn_runtime", default=None)


def set_runtime(runtime: TurnRuntime):
    return _RUNTIME.set(runtime)


def reset_runtime(token) -> None:
    _RUNTIME.reset(token)


def get_runtime() -> TurnRuntime:
    runtime = _RUNTIME.get()
    if runtime is None:
        raise RuntimeError("Turn graph ran without a TurnRuntime")
    return runtime
