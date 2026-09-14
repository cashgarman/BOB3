"""Example 09 - Driving the SDK from a script, the way a test would.

What this shows
---------------
Examples 01–07 drop a file into `data/tools/` and let Bob import it. This file
never does that. It uses the SDK as a library:

* `spec_from_function` builds a `ToolSpec` without the `@tool` global registry.
* `ToolRegistry.add` publishes that spec.
* `registry.context(...)` and `registry.invoke(...)` run it with a fake
  cancel event and a status callback you control.
* A tiny stand-in for `ctx.memory` shows how to test tools that call
  `memory.retrieve` without loading LanceDB.

Run this file directly; it is both the example and its own assertion suite:

    .venv\\Scripts\\python.exe sdk_examples\\09_testing_registry.py

Nothing here is loaded by Bob at boot. Copy patterns out of it into your
own tests; do not copy the file into `data\\tools\\`.
"""

from __future__ import annotations

# `tempfile` gives each run its own data_dir so we never touch Bob's real `data/`.
import tempfile
import threading
from pathlib import Path

from bob.tools import ToolContext, ToolError, ToolRegistry, spec_from_function, tool


# ---------------------------------------------------------------------------
# The functions under test. They are written exactly like production tools.
# ---------------------------------------------------------------------------


def ping() -> str:
    """Return a short ready-check string."""
    return "pong"


def greet(name: str, excited: bool = False) -> str:
    """Greet someone by name.

    Args:
        name: Who to greet.
        excited: Whether to shout.
    """
    text = name.strip()
    if not text:
        raise ToolError("name is empty")
    greeting = f"Hello, {text}!"
    return greeting.upper() if excited else greeting


@tool
def memory_blurb(query: str, *, ctx: ToolContext) -> str:
    """Return whatever long-term memory knows about a query.

    Decorated so we can also show `declared_tools` / `@tool` in a test, but
    this module is imported as a script, not as a `data/tools/` plugin.
    """
    memory = ctx.memory
    if memory is None or not getattr(memory, "ready", False):
        raise ToolError("memory is offline")
    found = memory.retrieve(query, limit=3)
    return found or f"nothing about {query}"


class FakeMemory:
    """Stand-in for MemoryService. Only the attributes tools actually touch."""

    ready = True

    def retrieve(self, query: str, limit: int = 8) -> str:
        # Production retrieve() returns a ready-to-inject block or "".
        if "color" in query.lower():
            return "Known about the user:\n- favorite color is green"
        return ""


# ---------------------------------------------------------------------------
# Helpers that mimic how you would structure a real test.
# ---------------------------------------------------------------------------


def make_registry(data_dir: Path, memory=None) -> ToolRegistry:
    """A registry with no built-ins and no plugins — only what we add."""
    registry = ToolRegistry(data_dir, memory=memory)
    # Skip registry.load(): that would import built-ins and data/tools/*.py.
    registry.add(spec_from_function(ping))
    registry.add(spec_from_function(greet))
    # `@tool` already built a spec; pull it off the function via spec_from_function
    # again so this registry does not depend on the process-global table.
    registry.add(spec_from_function(memory_blurb))
    return registry


def expect(label: str, actual: str, fragment: str) -> None:
    """Print a pass/fail line. Exits non-zero at the end if anything failed."""
    ok = fragment.lower() in actual.lower()
    mark = "ok" if ok else "FAIL"
    print(f"  [{mark}] {label}")
    if not ok:
        print(f"         got: {actual!r}")
        print(f"         expected to contain: {fragment!r}")
        expect.failed += 1


expect.failed = 0


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        registry = make_registry(data_dir, memory=FakeMemory())
        ctx = registry.context(
            cancel=threading.Event(),
            status=lambda msg: print(f"         [status] {msg}"),
        )

        print("inventory")
        names = registry.names()
        expect("registered ping, greet, memory_blurb", ", ".join(names), "greet")
        schema = next(spec.schema()["function"] for spec in registry.specs() if spec.name == "greet")
        # ctx must never appear; excited is optional because it has a default.
        expect("greet schema has name", str(schema["parameters"]["required"]), "name")
        expect("greet schema hides no ctx", str(schema["parameters"]["properties"]), "name")
        if "ctx" in schema["parameters"]["properties"]:
            expect("ctx leaked into schema", "ctx in properties", "no ctx")

        print("happy path")
        expect("ping", registry.invoke("ping", {}, ctx), "pong")
        expect("greet", registry.invoke("greet", {"name": "Ada"}, ctx), "Hello, Ada!")
        # Coercion: the model sent a string for a bool.
        expect("greet shouted", registry.invoke("greet", {"name": "Ada", "excited": "true"}, ctx), "HELLO, ADA!")

        print("errors stay strings")
        missing = registry.invoke("greet", {}, ctx)
        expect("missing arg", missing, "missing required argument")
        empty = registry.invoke("greet", {"name": "  "}, ctx)
        expect("ToolError", empty, "name is empty")
        unknown = registry.invoke("no_such_tool", {}, ctx)
        expect("unknown tool", unknown, "there is no tool named")

        print("memory double")
        hit = registry.invoke("memory_blurb", {"query": "favorite color"}, ctx)
        expect("memory hit", hit, "green")
        miss = registry.invoke("memory_blurb", {"query": "pets"}, ctx)
        expect("memory miss", miss, "nothing about pets")

        print("offline memory")
        offline = make_registry(data_dir, memory=None)
        down = offline.invoke("memory_blurb", {"query": "color"}, offline.context())
        expect("memory offline", down, "memory is offline")
        offline.close()

        registry.close()

    if expect.failed:
        print(f"\n{expect.failed} check(s) failed")
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
