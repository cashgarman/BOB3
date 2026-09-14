from __future__ import annotations

import inspect
import json
import types
import typing
from collections.abc import Callable
from typing import Any, Literal, get_args, get_origin

from bob.tools.base import ToolContext, ToolError, ToolSpec, sanitize_name

_CONTEXT_NAMES = {"ctx", "context", "bob"}
_SCALARS: dict[Any, str] = {
    str: "string",
    bool: "boolean",
    int: "integer",
    float: "number",
}


def spec_from_function(
    fn: Callable[..., Any],
    *,
    name: str | None = None,
    description: str | None = None,
    parameters: dict[str, Any] | None = None,
    source: str = "sdk",
) -> ToolSpec:
    summary, arg_docs = _split_docstring(inspect.getdoc(fn) or "")
    hints = _hints(fn)
    signature = inspect.signature(fn)
    return ToolSpec(
        name=sanitize_name(name or fn.__name__),
        description=(description or summary or fn.__name__.replace("_", " ")).strip(),
        parameters=parameters or _parameters(signature, hints, arg_docs),
        run=_runner(fn, signature, hints),
        source=source,
    )


def _hints(fn: Callable[..., Any]) -> dict[str, Any]:
    try:
        return typing.get_type_hints(fn)
    except Exception:
        return {}


def _is_context(param_name: str, annotation: Any) -> bool:
    if annotation is ToolContext:
        return True
    if isinstance(annotation, str) and annotation.split(".")[-1].rstrip("]") == "ToolContext":
        return True
    # `ctx: ToolContext = None` reaches us as ToolContext | None.
    if get_origin(annotation) in {typing.Union, types.UnionType}:
        return any(arg is ToolContext for arg in get_args(annotation))
    return annotation is inspect.Parameter.empty and param_name.lower() in _CONTEXT_NAMES


def _parameters(
    signature: inspect.Signature,
    hints: dict[str, Any],
    arg_docs: dict[str, str],
) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    for param_name, param in signature.parameters.items():
        if param.kind in {param.VAR_POSITIONAL, param.VAR_KEYWORD}:
            continue
        annotation = hints.get(param_name, param.annotation)
        if _is_context(param_name, annotation):
            continue
        prop = _json_type(annotation)
        doc = arg_docs.get(param_name)
        if doc:
            prop["description"] = doc
        if param.default is inspect.Parameter.empty:
            required.append(param_name)
        elif _jsonable(param.default):
            prop["default"] = param.default
        properties[param_name] = prop
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _json_type(annotation: Any) -> dict[str, Any]:
    if annotation is inspect.Parameter.empty or annotation is Any:
        return {"type": "string"}
    origin = get_origin(annotation)
    if origin is Literal:
        options = [opt for opt in get_args(annotation) if _jsonable(opt)]
        base = _SCALARS.get(type(options[0]), "string") if options else "string"
        return {"type": base, "enum": options}
    if origin in {typing.Union, types.UnionType}:
        inner = [arg for arg in get_args(annotation) if arg is not type(None)]
        return _json_type(inner[0]) if inner else {"type": "string"}
    if origin in {list, set, tuple, frozenset}:
        args = get_args(annotation)
        items = _json_type(args[0]) if args else {"type": "string"}
        return {"type": "array", "items": items}
    if origin is dict:
        return {"type": "object"}
    if annotation in _SCALARS:
        return {"type": _SCALARS[annotation]}
    if annotation in {list, set, tuple}:
        return {"type": "array", "items": {"type": "string"}}
    if annotation is dict:
        return {"type": "object"}
    return {"type": "string"}


def _jsonable(value: Any) -> bool:
    return isinstance(value, (str, bool, int, float))


def _runner(
    fn: Callable[..., Any],
    signature: inspect.Signature,
    hints: dict[str, Any],
) -> Callable[[dict[str, Any], ToolContext], Any]:
    def run(arguments: dict[str, Any], ctx: ToolContext) -> Any:
        kwargs: dict[str, Any] = {}
        for param_name, param in signature.parameters.items():
            if param.kind in {param.VAR_POSITIONAL, param.VAR_KEYWORD}:
                continue
            annotation = hints.get(param_name, param.annotation)
            if _is_context(param_name, annotation):
                kwargs[param_name] = ctx
                continue
            if param_name in arguments and arguments[param_name] is not None:
                kwargs[param_name] = _coerce(arguments[param_name], annotation)
            elif param.default is inspect.Parameter.empty:
                raise ToolError(f"missing required argument '{param_name}'")
        return fn(**kwargs)

    return run


def _coerce(value: Any, annotation: Any) -> Any:
    target = _json_type(annotation).get("type")
    if target == "string":
        return value if isinstance(value, str) else json.dumps(value, default=str)
    if target == "boolean":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}
    if target in {"integer", "number"}:
        if isinstance(value, bool):
            return int(value)
        try:
            number = float(str(value).strip())
        except ValueError as exc:
            raise ToolError(f"expected a number, got {value!r}") from exc
        return int(number) if target == "integer" else number
    if target == "array" and isinstance(value, str):
        try:
            loaded = json.loads(value)
        except json.JSONDecodeError:
            return [part.strip() for part in value.split(",") if part.strip()]
        return loaded if isinstance(loaded, list) else [loaded]
    return value


def _split_docstring(doc: str) -> tuple[str, dict[str, str]]:
    """Return the summary text and any Google-style `Args:` descriptions."""
    summary: list[str] = []
    arg_docs: dict[str, str] = {}
    section = "summary"
    current = ""
    for raw_line in doc.splitlines():
        line = raw_line.strip()
        lowered = line.lower().rstrip(":")
        if lowered in {"args", "arguments", "parameters"} and line.endswith(":"):
            section = "args"
            continue
        if lowered in {"returns", "return", "raises", "examples", "example", "notes"} and line.endswith(":"):
            section = "other"
            continue
        if section == "summary":
            summary.append(line)
        elif section == "args":
            if ":" in line:
                head, _, text = line.partition(":")
                current = head.split("(")[0].strip()
                if current:
                    arg_docs[current] = text.strip()
            elif line and current:
                arg_docs[current] = f"{arg_docs[current]} {line}".strip()
    return " ".join(part for part in summary if part).strip(), arg_docs
