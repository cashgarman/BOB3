from __future__ import annotations

import asyncio
import json
import os
import threading
from concurrent.futures import Future
from typing import Any

from mcp import Client, StdioServerParameters

from bob.tools.base import ToolContext, ToolError, ToolSpec, sanitize_name

CONNECT_GRACE_SEC = 10.0
STOP_WAIT_SEC = 5.0


class McpHub:
    """Owns MCP connections on one asyncio thread and exposes them as ToolSpecs.

    Bob is threaded and synchronous, so every session lives in a task on this
    hub's private loop and calls are handed to it with run_coroutine_threadsafe.
    """

    def __init__(self, servers: list[dict[str, Any]], timeout: float = 20.0) -> None:
        self.servers = servers
        self.timeout = max(1.0, float(timeout))
        self.errors: list[str] = []
        self._loop = asyncio.new_event_loop()
        self._thread: threading.Thread | None = None
        self._stop = asyncio.Event()
        self._clients: dict[str, Any] = {}
        self._tasks: list[Future] = []

    def start(self) -> list[ToolSpec]:
        self._thread = threading.Thread(target=self._run_loop, name="mcp", daemon=True)
        self._thread.start()
        specs: list[ToolSpec] = []
        for config in self.servers:
            server_id = sanitize_name(config.get("id") or config.get("name") or "mcp")
            ready: Future = Future()
            task = asyncio.run_coroutine_threadsafe(self._serve(config, server_id, ready), self._loop)
            self._tasks.append(task)
            try:
                tools = ready.result(timeout=self.timeout + CONNECT_GRACE_SEC)
            except Exception as exc:
                self.errors.append(f"{server_id}: {_reason(exc)}")
                continue
            for tool in tools:
                specs.append(self._spec(server_id, tool))
        return specs

    def stop(self) -> None:
        if self._loop.is_closed():
            return
        try:
            self._loop.call_soon_threadsafe(self._stop.set)
        except RuntimeError:
            pass
        for task in self._tasks:
            try:
                task.result(timeout=STOP_WAIT_SEC)
            except Exception:
                pass
        self._tasks.clear()
        self._clients.clear()
        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=STOP_WAIT_SEC)
            self._thread = None

    def call(self, server_id: str, tool_name: str, arguments: dict[str, Any], timeout: float) -> str:
        client = self._clients.get(server_id)
        if client is None:
            raise ToolError(f"MCP server '{server_id}' is not connected")
        future = asyncio.run_coroutine_threadsafe(
            client.call_tool(tool_name, arguments or None),
            self._loop,
        )
        try:
            result = future.result(timeout=max(1.0, float(timeout)))
        except TimeoutError as exc:
            future.cancel()
            raise ToolError(f"MCP server '{server_id}' did not answer in time") from exc
        return _result_text(result)

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_forever()
        finally:
            try:
                self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            except Exception:
                pass
            self._loop.close()

    async def _serve(self, config: dict[str, Any], server_id: str, ready: Future) -> None:
        """Hold one session open until stop() so its subprocess stays alive."""
        try:
            async with Client(_transport(config), read_timeout_seconds=self.timeout) as client:
                tools = await _list_tools(client)
                self._clients[server_id] = client
                ready.set_result(tools)
                await self._stop.wait()
        except Exception as exc:
            if not ready.done():
                ready.set_exception(exc)
        finally:
            self._clients.pop(server_id, None)

    def _spec(self, server_id: str, tool: Any) -> ToolSpec:
        tool_name = str(getattr(tool, "name", "") or "tool")
        schema = getattr(tool, "input_schema", None) or getattr(tool, "inputSchema", None) or {}
        description = (
            getattr(tool, "description", None)
            or getattr(tool, "title", None)
            or f"{tool_name} from the {server_id} MCP server"
        )

        def run(arguments: dict[str, Any], ctx: ToolContext) -> str:
            return self.call(server_id, tool_name, arguments, self.timeout)

        return ToolSpec(
            name=sanitize_name(f"{server_id}_{tool_name}"),
            description=str(description).strip(),
            parameters=dict(schema) if isinstance(schema, dict) else {"type": "object", "properties": {}},
            run=run,
            source=f"mcp:{server_id}",
        )


def _transport(config: dict[str, Any]) -> Any:
    url = str(config.get("url") or "").strip()
    if url:
        return url
    command = str(config.get("command") or "").strip()
    if not command:
        raise ToolError("server needs either a 'url' or a 'command'")
    args = [str(arg) for arg in config.get("args") or []]
    env = config.get("env")
    return StdioServerParameters(
        command=command,
        args=args,
        env={**_base_env(), **{str(k): str(v) for k, v in env.items()}} if env else None,
        cwd=config.get("cwd") or None,
    )


def _base_env() -> dict[str, str]:
    try:
        from mcp.client.stdio import get_default_environment

        return dict(get_default_environment())
    except Exception:
        return dict(os.environ)


async def _list_tools(client: Any) -> list[Any]:
    tools: list[Any] = []
    cursor: str | None = None
    while True:
        page = await client.list_tools(cursor=cursor)
        tools.extend(page.tools)
        cursor = getattr(page, "next_cursor", None) or getattr(page, "nextCursor", None)
        if not cursor or len(tools) > 200:
            return tools


def _result_text(result: Any) -> str:
    parts: list[str] = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(str(text))
        else:
            parts.append(f"[{getattr(block, 'type', 'content')}]")
    if not parts:
        structured = getattr(result, "structured_content", None) or getattr(result, "structuredContent", None)
        if structured is not None:
            try:
                parts.append(json.dumps(structured, ensure_ascii=False, default=str))
            except (TypeError, ValueError):
                parts.append(str(structured))
    text = "\n".join(part for part in parts if part).strip() or "done"
    failed = getattr(result, "is_error", None) or getattr(result, "isError", None)
    return f"Error: {text}" if failed else text


def _reason(exc: BaseException) -> str:
    # anyio task groups wrap the real failure, which is what a user needs to see.
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    message = str(exc).strip()
    return message or exc.__class__.__name__
