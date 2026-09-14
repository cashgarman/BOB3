"""Run any SDK example without the voice pipeline.

This is the development loop for tool authors. It loads one example file (or
an MCP server), registers its tools exactly the way Bob does at boot, and then
lets you inspect or exercise them:

    --schema                Print the JSON the model sees (default action)
    --call NAME k=v ...     Invoke one tool directly and print its result
    --chat                  Text chat with your Ollama model, tools enabled

Examples
--------
    .venv\\Scripts\\python.exe sdk_examples\\run_example.py 02_typed_arguments.py
    .venv\\Scripts\\python.exe sdk_examples\\run_example.py 02_typed_arguments.py --call split_bill total=84.5 people=3
    .venv\\Scripts\\python.exe sdk_examples\\run_example.py 07_stateful_todo_list.py --chat
    .venv\\Scripts\\python.exe sdk_examples\\run_example.py --mcp kitchen=sdk_examples/08_mcp_server/server.py --schema
    .venv\\Scripts\\python.exe sdk_examples\\run_example.py --mcp-url kitchen=http://127.0.0.1:8765/mcp --chat

Argument values after --call are parsed as JSON when possible (`people=3`
becomes an int, `prices=[1,2]` a list, `on=false` a bool) and kept as strings
otherwise, which mirrors what a model would send.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import threading
from pathlib import Path

# Make `import bob` work no matter where the script is launched from.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bob.llm import OllamaChat  # noqa: E402
from bob.settings import DATA_DIR, load_settings  # noqa: E402
from bob.tools import ToolRegistry, declared_tools  # noqa: E402

EXAMPLES_DIR = Path(__file__).resolve().parent


def import_example(spec_path: str) -> Path:
    """Import an example file so its `@tool` decorators run."""
    path = Path(spec_path)
    if not path.is_absolute():
        # Accept "02_typed_arguments.py" as well as a path relative to the repo.
        candidate = EXAMPLES_DIR / path
        path = candidate if candidate.exists() else (ROOT / path)
    if not path.exists():
        sys.exit(f"example not found: {spec_path}")
    spec = importlib.util.spec_from_file_location(f"sdk_example_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return path


def parse_kv(pairs: list[str]) -> dict:
    """Turn ["a=1", "b=hello", "c=[1,2]"] into {"a": 1, "b": "hello", "c": [1, 2]}."""
    arguments: dict = {}
    for pair in pairs:
        if "=" not in pair:
            sys.exit(f"expected key=value, got {pair!r}")
        key, _, raw = pair.partition("=")
        try:
            arguments[key] = json.loads(raw)
        except json.JSONDecodeError:
            arguments[key] = raw
    return arguments


def parse_server(spec: str, key: str) -> dict:
    """'kitchen=path/or/url' -> {"id": "kitchen", key: "path/or/url"}."""
    if "=" not in spec:
        sys.exit(f"--{key} needs the form id={key}, got {spec!r}")
    server_id, _, target = spec.partition("=")
    server = {"id": server_id, "enabled": True}
    if key == "url":
        server["url"] = target
    else:
        server["command"] = sys.executable
        server["args"] = [str((ROOT / target).resolve() if not Path(target).is_absolute() else target)]
    return server


def print_schemas(registry: ToolRegistry, names: list[str]) -> None:
    for spec in registry.specs():
        if spec.name in names:
            print(f"\n# {spec.name}  ({spec.source})")
            print(json.dumps(spec.schema()["function"], indent=2, ensure_ascii=False))


def chat(registry: ToolRegistry, settings, timeout: float) -> None:
    llm = OllamaChat(
        settings.ollama_host,
        settings.llm_model,
        settings.llm_num_ctx,
        settings.system_prompt,
        settings.max_history_turns,
    )
    try:
        llm.ping()
    except Exception as exc:
        sys.exit(f"Ollama is not reachable at {settings.ollama_host}: {exc}")
    cancel = threading.Event()
    ctx = registry.context(cancel=cancel, status=lambda msg: print(f"   [status] {msg}"), on_mood=lambda m: print(f"   [mood] {m}"))

    def on_tool(name: str, arguments) -> str:
        print(f"   [tool] {name} {json.dumps(arguments, ensure_ascii=False)}")
        result = registry.invoke(name, arguments, ctx=ctx, timeout=timeout)
        print(f"   [result] {result[:300]}{'...' if len(result) > 300 else ''}")
        return result

    print(f"Chatting with {settings.llm_model}; {len(registry.names())} tools available. Empty line or Ctrl+C to quit.")
    while True:
        try:
            text = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not text:
            break
        print("bob> ", end="", flush=True)
        try:
            for chunk in llm.chat(
                text,
                tools=registry.schemas(),
                on_tool=on_tool,
                cancel=cancel,
                max_rounds=int(settings.max_tool_rounds),
            ):
                print(chunk, end="", flush=True)
        except Exception as exc:
            print(f"\n[error] {exc}")
        print()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("example", nargs="?", help="example file, e.g. 01_hello_tool.py")
    parser.add_argument("--mcp", action="append", default=[], metavar="ID=PATH", help="stdio MCP server to launch")
    parser.add_argument("--mcp-url", action="append", default=[], metavar="ID=URL", help="Streamable HTTP MCP server")
    parser.add_argument("--schema", action="store_true", help="print the tool schemas (default)")
    parser.add_argument("--call", nargs="+", metavar=("NAME", "KEY=VALUE"), help="invoke one tool directly")
    parser.add_argument("--chat", action="store_true", help="interactive text chat with tools")
    parser.add_argument("--all", action="store_true", help="include built-ins and data/tools in --schema output")
    parser.add_argument("--timeout", type=float, help="tool timeout in seconds (default from config)")
    parser.add_argument("--memory", action="store_true", help="load long-term memory so ctx.memory works")
    args = parser.parse_args()
    if not args.example and not args.mcp and not args.mcp_url:
        parser.error("give an example file, --mcp, or --mcp-url")

    settings = load_settings()
    timeout = args.timeout or float(settings.tool_timeout_sec)

    memory = None
    if args.memory:
        from bob.memory.service import MemoryService

        memory = MemoryService(DATA_DIR / "memory")
        print("loading memory ...")
        memory.load()

    # `load()` always imports built-ins + data/tools. Snapshot the global
    # `@tool` table first, then import the example so we can tell its tools
    # apart from everything else when printing --schema.
    registry = ToolRegistry(DATA_DIR, settings=settings, memory=memory)
    registry.load()
    before_ids = {id(spec) for spec in declared_tools()}
    if args.example:
        print(f"loaded {import_example(args.example).name}")
    example_names = []
    for spec in declared_tools():
        registry.add(spec)
        if id(spec) not in before_ids:
            example_names.append(spec.name)
    example_names.sort()

    servers = [parse_server(spec, "command") for spec in args.mcp] + [parse_server(spec, "url") for spec in args.mcp_url]
    if servers:
        print(f"connecting {len(servers)} MCP server(s) ...")
        example_names += registry.load_mcp(servers, timeout=timeout)

    for err in registry.errors:
        print(f"warning: {err}")
    if example_names:
        print("example tools:", ", ".join(example_names))
    else:
        print("no tools were registered by the example")

    try:
        if args.call:
            name, *pairs = args.call
            arguments = parse_kv(pairs)
            ctx = registry.context(
                status=lambda msg: print(f"   [status] {msg}"),
                on_mood=lambda m: print(f"   [mood] {m}"),
            )
            print(f"\n{name}({json.dumps(arguments, ensure_ascii=False)})")
            print("->", registry.invoke(name, arguments, ctx=ctx, timeout=timeout))
        elif args.chat:
            chat(registry, settings, timeout)
        else:
            print_schemas(registry, registry.names() if args.all else example_names)
    finally:
        registry.close()


if __name__ == "__main__":
    main()
