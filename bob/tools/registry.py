from __future__ import annotations

import importlib
import importlib.util
import sys
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from pathlib import Path
from typing import Any

from bob.tools.base import ToolContext, ToolSpec, clip_result, parse_arguments
from bob.tools.schema import spec_from_function

BUILTIN_MODULES = (
    "bob.tools.builtin.clock",
    "bob.tools.builtin.web",
    "bob.tools.builtin.notes",
    "bob.tools.builtin.recall",
    "bob.tools.builtin.mood",
)

_DECLARED: dict[str, ToolSpec] = {}


def tool(
    fn: Callable[..., Any] | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
    parameters: dict[str, Any] | None = None,
):
    """Register a function as a Bob tool. Usable bare or with keywords."""

    def wrap(func: Callable[..., Any]) -> Callable[..., Any]:
        spec = spec_from_function(func, name=name, description=description, parameters=parameters)
        _DECLARED[spec.name] = spec
        return func

    return wrap(fn) if callable(fn) else wrap


def declared_tools() -> list[ToolSpec]:
    return list(_DECLARED.values())


class ToolRegistry:
    def __init__(self, data_dir: Path, settings: Any = None, memory: Any = None) -> None:
        self.data_dir = Path(data_dir)
        self.plugin_dir = self.data_dir / "tools"
        self.settings = settings
        self.memory = memory
        self.errors: list[str] = []
        self._tools: dict[str, ToolSpec] = {}
        self._lock = threading.Lock()
        self._executor: ThreadPoolExecutor | None = None
        self._mcp = None

    def load(self) -> list[str]:
        """Import built-ins and user plugins, then publish them as tools."""
        self.errors = [err for err in self.errors if err.startswith("mcp")]
        # Start from a clean slate so a plugin file that was deleted or renamed
        # since the last load does not keep offering its old tools.
        _DECLARED.clear()
        for module in BUILTIN_MODULES:
            try:
                loaded = sys.modules.get(module)
                if loaded is not None:
                    importlib.reload(loaded)
                else:
                    importlib.import_module(module)
            except Exception as exc:
                self.errors.append(f"builtin {module}: {exc}")
        self._load_plugins()
        with self._lock:
            self._tools = {name: spec for name, spec in self._tools.items() if spec.is_mcp}
        for spec in declared_tools():
            self.add(spec)
        return self.names()

    def _load_plugins(self) -> None:
        try:
            self.plugin_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.errors.append(f"plugin dir: {exc}")
            return
        for path in sorted(self.plugin_dir.glob("*.py")):
            if path.name.startswith("_"):
                continue
            try:
                spec = importlib.util.spec_from_file_location(f"bob_user_tools.{path.stem}", path)
                if spec is None or spec.loader is None:
                    raise ImportError("could not build a module spec")
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
            except Exception as exc:
                self.errors.append(f"{path.name}: {exc}")

    def load_mcp(self, servers: list[dict[str, Any]], timeout: float = 20.0) -> list[str]:
        """Connect MCP servers and register their tools alongside SDK tools."""
        enabled = [srv for srv in servers or [] if isinstance(srv, dict) and srv.get("enabled", True)]
        if not enabled:
            return []
        try:
            from bob.tools.mcp_hub import McpHub
        except ImportError as exc:
            self.errors.append(f"mcp unavailable: {exc}")
            return []
        self.close_mcp()
        hub = McpHub(enabled, timeout=timeout)
        specs = hub.start()
        self.errors.extend(f"mcp {err}" for err in hub.errors)
        self._mcp = hub
        added = []
        for spec in specs:
            if self.add(spec):
                added.append(spec.name)
        return added

    def add(self, spec: ToolSpec) -> bool:
        with self._lock:
            existing = self._tools.get(spec.name)
            if existing is not None and spec.is_mcp and not existing.is_mcp:
                self.errors.append(f"mcp tool {spec.name} skipped: name already used by an SDK tool")
                return False
            self._tools[spec.name] = spec
            return True

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._tools)

    def specs(self) -> list[ToolSpec]:
        with self._lock:
            return [self._tools[name] for name in sorted(self._tools)]

    def schemas(self) -> list[dict[str, Any]]:
        return [spec.schema() for spec in self.specs()]

    def context(
        self,
        cancel: threading.Event | None = None,
        status: Callable[[str], None] | None = None,
        mood: str | None = None,
        on_mood: Callable[[str], None] | None = None,
    ) -> ToolContext:
        from bob.voice_mood import resolve_mood

        ctx = ToolContext(
            cancel=cancel or threading.Event(),
            settings=self.settings,
            memory=self.memory,
            data_dir=self.data_dir,
            _mood=resolve_mood(mood),
        )
        if status is not None:
            ctx.status = status
        if on_mood is not None:
            ctx._on_mood = on_mood
        return ctx

    def invoke(
        self,
        name: str,
        arguments: Any,
        ctx: ToolContext | None = None,
        timeout: float = 20.0,
    ) -> str:
        """Run a tool and always return model-readable text, never raise."""
        with self._lock:
            spec = self._tools.get(name)
        if spec is None:
            known = ", ".join(self.names()) or "none"
            return f"Error: there is no tool named '{name}'. Available tools: {known}."
        ctx = ctx or self.context()
        args = parse_arguments(arguments)
        limit = max(1.0, float(timeout or 20.0))
        try:
            future = self._pool().submit(spec.run, args, ctx)
            return clip_result(future.result(timeout=limit))
        except FutureTimeout:
            return f"Error: tool '{name}' timed out after {limit:.0f}s."
        except Exception as exc:
            return f"Error: tool '{name}' failed: {exc}"

    def _pool(self) -> ThreadPoolExecutor:
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="tool")
        return self._executor

    def close_mcp(self) -> None:
        hub, self._mcp = self._mcp, None
        if hub is None:
            return
        try:
            hub.stop()
        except Exception:
            pass
        with self._lock:
            self._tools = {name: spec for name, spec in self._tools.items() if not spec.is_mcp}

    def close(self) -> None:
        self.close_mcp()
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None
