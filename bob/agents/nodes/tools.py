from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from bob.agents.state import TurnState, get_runtime
from bob.llm import (
    _deferral_tool_args,
    _deferral_tool_name,
    _fallback_bullets_from_search,
    _fallback_headlines_from_search,
    _finalize_spoken_reply,
    _format_calendar_tool_result,
    _format_time_tool_result,
    _fresh_web_search,
    _invoke_conversation_log,
    _invoke_web_search,
    _is_internal_monologue,
    _is_tool_preamble,
    _is_tools_unsupported_error,
    _is_useless_reply,
    _is_web_search_followup,
    _looks_like_spoken_answer,
    _strip_control_tokens,
    _strip_think_blocks,
    _try_direct_answer,
    _user_wants_bullets,
    _web_search_followup_query,
    PROMPT_FILE_FOR_REFLECT,
    format_prompt_catalog_reply,
    format_prompt_edit_fallback,
    format_prompt_reflect_fallback,
    format_prompt_spoken_reply,
    needs_chat_context,
    needs_current_time,
    needs_prompt_files,
    wants_prompt_catalog_list,
    wants_prompt_edit,
    wants_prompt_edit_followup,
    wants_prompt_reflection,
    wants_verbatim_system_prompt,
)

log = logging.getLogger(__name__)


def consume_round(
    llm: Any,
    system: str,
    tools: list[dict[str, Any]] | None,
    cancel: Any,
    spoken: list[str],
    spoken_user: str,
    on_thought: Callable[[str], None] | None,
) -> tuple[str, list]:
    gen = llm._round(system, tools, cancel, spoken, spoken_user, on_thought)
    while True:
        try:
            chunk = next(gen)
        except StopIteration as exc:
            value = exc.value
            if isinstance(value, tuple) and len(value) == 2:
                return str(value[0] or ""), list(value[1] or [])
            return "", []
        except GeneratorExit:
            raise


def tools_node(state: TurnState) -> dict[str, Any]:
    runtime = get_runtime()
    llm = runtime.llm
    user_text = str(state.get("user_text") or "")
    memory_block = str(state.get("memory_block") or "")
    kind = str(state.get("route_kind") or "")
    on_tool = runtime.on_tool
    on_thought = runtime.on_thought
    tools = None if llm._tools_unsupported else runtime.tools
    results: list[tuple[str, str]] = []

    if kind == "prompts" and on_tool:
        branch = "verbatim"
        if wants_prompt_edit(user_text, llm.history) or wants_prompt_edit_followup(user_text, llm.history):
            branch = "edit"
        elif wants_prompt_reflection(user_text):
            branch = "reflect"
        elif wants_prompt_catalog_list(user_text):
            branch = "catalog"
        elif wants_verbatim_system_prompt(user_text):
            branch = "verbatim"
        else:
            branch = "catalog"
        if branch == "edit":
            llm._append_internal_thought("Prompt edit: reading system prompt from disk.", on_thought)
            try:
                system_text = on_tool("read_file", {"path": "prompts/system.txt"})
            except Exception as exc:
                system_text = f"Error: tool 'read_file' failed: {exc}"
            llm.history.append(
                {"role": "tool", "tool_name": "read_file", "content": f"prompts/system.txt\n{system_text}"}
            )
            results = [("read_file", system_text)]
            new_prompt, spoken = format_prompt_edit_fallback(system_text)
            if not new_prompt or new_prompt.strip() == (system_text or "").strip():
                new_prompt, spoken = llm.synthesize_system_prompt_edit(
                    user_text,
                    system_text,
                    on_thought=on_thought,
                )
            if new_prompt and new_prompt.strip() != (system_text or "").strip():
                try:
                    write_result = on_tool(
                        "write_file",
                        {"path": "prompts/system.txt", "content": new_prompt},
                    )
                except Exception as exc:
                    write_result = f"Error: tool 'write_file' failed: {exc}"
                llm.history.append(
                    {
                        "role": "tool",
                        "tool_name": "write_file",
                        "content": f"prompts/system.txt\n{write_result}",
                    }
                )
                results.append(("write_file", write_result))
            reply = spoken
            if not reply and new_prompt and new_prompt.strip() != (system_text or "").strip():
                reply = "Done — I updated my system prompt."
            if not reply:
                reply = "I couldn't update my system prompt right now."
            llm.history.append({"role": "assistant", "content": reply})
            return _spoken_update(reply, used_tools=True, results=results, trusted=True)

        if branch == "reflect":
            llm._append_internal_thought("Prompt reflection: reading system prompt from disk.", on_thought)
            results: list[tuple[str, str]] = []
            try:
                system_body = on_tool("read_file", {"path": "prompts/system.txt"})
            except Exception as exc:
                system_body = f"Error: tool 'read_file' failed: {exc}"
            llm.history.append(
                {"role": "tool", "tool_name": "read_file", "content": f"prompts/system.txt\n{system_body}"}
            )
            results.append(("read_file", system_body))
            reply = format_prompt_reflect_fallback(system_body)
            llm._append_internal_thought("Reflected on the prompt files.", on_thought)
            if reply:
                llm.history.append({"role": "assistant", "content": reply})
            if reply:
                return _spoken_update(reply, used_tools=True, results=results, trusted=True)

        llm._append_internal_thought("Prompt question: reading prompt catalog from disk.", on_thought)
        try:
            catalog = on_tool("list_prompts", {})
        except Exception as exc:
            catalog = f"Error: tool 'list_prompts' failed: {exc}"
        llm.history.append({"role": "tool", "tool_name": "list_prompts", "content": catalog})
        results: list[tuple[str, str]] = [("list_prompts", catalog)]

        if branch == "catalog":
            reply = format_prompt_catalog_reply(catalog)
            llm._append_internal_thought("Summarized the prompt files.", on_thought)
            if reply:
                llm.history.append({"role": "assistant", "content": reply})
            if reply:
                return _spoken_update(reply, used_tools=True, results=results, trusted=True)

        system_text = ""
        try:
            system_text = on_tool("read_file", {"path": "prompts/system.txt"})
        except Exception as exc:
            system_text = f"Error: tool 'read_file' failed: {exc}"
        llm.history.append({"role": "tool", "tool_name": "read_file", "content": system_text})
        results.append(("read_file", system_text))
        reply = format_prompt_spoken_reply(user_text, catalog, system_text)
        if reply:
            llm._append_internal_thought("Spoke the prompt file contents.", on_thought)
            llm.history.append({"role": "assistant", "content": reply})
            return _spoken_update(reply, used_tools=True, results=results, trusted=True)

    if kind == "calendar" and on_tool:
        llm._append_internal_thought("Calendar question: calling get_current_time.", on_thought)
        try:
            result = on_tool("get_current_time", {})
        except Exception as exc:
            result = f"Error: tool 'get_current_time' failed: {exc}"
        llm.history.append({"role": "tool", "tool_name": "get_current_time", "content": result})
        reply = _format_calendar_tool_result(user_text, result)
        if reply:
            llm._append_internal_thought("Spoke the calendar fact from the clock.", on_thought)
            llm.history.append({"role": "assistant", "content": reply})
            return _spoken_update(reply, used_tools=True, results=[("get_current_time", result)])

    if kind == "web" and on_tool:
        reply = llm._answer_from_web_search(user_text, on_tool, on_thought)
        if reply:
            return _spoken_update(reply, used_tools=True, results=[("web_search", "")])
    if kind == "web_followup" and on_tool:
        query = _web_search_followup_query(llm.history, user_text)
        reply = llm._answer_from_web_search(
            user_text,
            on_tool,
            on_thought,
            query=query,
            thought="Retried the web search using your earlier request.",
        )
        if reply:
            return _spoken_update(reply, used_tools=True, results=[("web_search", "")])

    if not tools or on_tool is None:
        return {"draft": "", "used_tools": False}

    return _run_tool_rounds(
        llm,
        user_text,
        memory_block=memory_block,
        tools=tools,
        on_tool=on_tool,
        on_thought=on_thought,
        cancel=runtime.cancel,
        max_rounds=int(runtime.max_rounds or 1),
        prior_results=results,
    )


def _spoken_update(
    reply: str,
    *,
    used_tools: bool,
    results: list[tuple[str, str]],
    trusted: bool = False,
) -> dict[str, Any]:
    return {
        "draft": reply,
        "spoken": reply,
        "chunks": [reply] if reply else [],
        "used_tools": used_tools,
        "tool_results": results,
        "gate_ok": bool(reply.strip()),
        "trusted_reply": trusted,
    }


def _run_tool_rounds(
    llm: Any,
    spoken_user: str,
    *,
    memory_block: str,
    tools: list[dict[str, Any]],
    on_tool: Callable[[str, Any], str],
    on_thought: Callable[[str], None] | None,
    cancel: Any,
    max_rounds: int,
    prior_results: list[tuple[str, str]],
) -> dict[str, Any]:
    tool_rounds = max(1, int(max_rounds))
    force_final = False
    streamed_to_user = False
    chunks: list[str] = []
    used_tools = False
    results = list(prior_results)

    for index in range(tool_rounds + 1):
        if cancel is not None and cancel.is_set():
            break
        if index > 0:
            llm._manage_context()
        offered = None if force_final or index >= tool_rounds else tools
        system = llm._system(with_tools=bool(offered), memory_block=memory_block)
        spoken: list[str] = []
        round_tools = offered
        try:
            content, calls = consume_round(
                llm, system, round_tools, cancel, spoken, spoken_user, on_thought
            )
        except GeneratorExit:
            partial = "".join(spoken).strip()
            if partial and not llm._history_ends_with_assistant(partial):
                llm.history.append({"role": "assistant", "content": partial})
            raise
        except RuntimeError as exc:
            if offered and _is_tools_unsupported_error(str(exc)):
                llm._tools_unsupported = True
                log.warning("Model %s does not support tools; continuing without tools", llm.model)
                system = llm._system(with_tools=False, memory_block=memory_block)
                round_tools = None
                content, calls = consume_round(
                    llm, system, round_tools, cancel, spoken, spoken_user, on_thought
                )
            else:
                raise
        if spoken:
            streamed_to_user = True
            chunks.extend(spoken)

        if not calls and offered and on_tool and (
            _is_tool_preamble(content) or _is_internal_monologue(content)
        ):
            hinted = _deferral_tool_name(content, spoken_user)
            if hinted:
                try:
                    args = _deferral_tool_args(hinted, spoken_user)
                    result = on_tool(hinted, args)
                except Exception as exc:
                    result = f"Error: tool '{hinted}' failed: {exc}"
                if content.strip():
                    llm.history.append({"role": "assistant", "content": content})
                llm.history.append({"role": "tool", "tool_name": hinted, "content": result})
                used_tools = True
                results.append((hinted, result))
                if hinted in {"web_search", "conversation_log"}:
                    reply = llm._finalize_tool_synthesis(spoken_user, memory_block, on_thought)
                    if not reply and hinted == "web_search":
                        reply = _search_fallback(spoken_user, result)
                        if reply:
                            llm._append_internal_thought(
                                "Used a deterministic summary of the search results.",
                                on_thought,
                            )
                            llm.history.append({"role": "assistant", "content": reply})
                    if reply:
                        return _spoken_update(reply, used_tools=True, results=results)
                continue

        if not calls and offered:
            probe = _strip_control_tokens(_strip_think_blocks(content))
            if probe and _is_useless_reply(probe, spoken_user):
                forced = _force_needed_tool(llm, spoken_user, on_tool, memory_block, on_thought)
                if forced:
                    used_tools = True
                    results.extend(forced[1])
                    return _spoken_update(forced[0], used_tools=True, results=results)
                continue

        if not calls and offered and content.strip() and _is_internal_monologue(content):
            log.warning(
                "Discarding internal monologue from tool round (%d chars, model=%s)",
                len(content),
                llm.model,
            )
            forced = _force_needed_tool(llm, spoken_user, on_tool, memory_block, on_thought)
            if forced:
                used_tools = True
                results.extend(forced[1])
                return _spoken_update(forced[0], used_tools=True, results=results)
            direct = _try_direct_answer(spoken_user)
            if direct:
                llm._append_internal_thought("Answered directly (skipped tool planning).", on_thought)
                llm.history.append({"role": "assistant", "content": direct})
                return _spoken_update(direct, used_tools=used_tools, results=results)
            force_final = True
            llm._append_internal_thought("Skipped tool planning; answering directly.", on_thought)
            continue

        if not calls and content.strip():
            content = _finalize_spoken_reply(content, llm.history, spoken_user)
        spoken_ok = bool(
            content.strip()
            and not _is_useless_reply(content, spoken_user)
            and _looks_like_spoken_answer(content, spoken_user)
        )
        if not calls and not spoken_ok:
            if needs_current_time(spoken_user) and on_tool:
                try:
                    result = on_tool("get_current_time", {})
                except Exception as exc:
                    result = f"Error: tool 'get_current_time' failed: {exc}"
                llm.history.append({"role": "tool", "tool_name": "get_current_time", "content": result})
                content = _format_time_tool_result(result)
                used_tools = True
                results.append(("get_current_time", result))
            elif offered:
                continue
            else:
                content = llm._recover_reply(
                    spoken_user,
                    memory_block=memory_block,
                    on_tool=on_tool,
                )
                llm._append_internal_thought(
                    "Initial model reply was unusable; regenerated a short answer.",
                    on_thought,
                )
            if content.strip() and not streamed_to_user:
                chunks.append(content)
        elif not calls and spoken_ok and round_tools:
            chunks.append(content)
            streamed_to_user = True
        if content.strip() or calls:
            message: dict[str, Any] = {"role": "assistant", "content": content}
            if calls:
                message["tool_calls"] = calls
            llm.history.append(message)
        if not calls:
            llm._trim()
            return _spoken_update(content, used_tools=used_tools, results=results)
        for call in calls:
            if cancel is not None and cancel.is_set():
                break
            function = call.get("function") or {}
            name = str(function.get("name") or "").strip()
            if not name:
                continue
            try:
                result = on_tool(name, function.get("arguments"))
            except Exception as exc:
                result = f"Error: tool '{name}' failed: {exc}"
            llm.history.append({"role": "tool", "tool_name": name, "content": result})
            used_tools = True
            results.append((name, result))
        if calls and on_tool:
            reply = llm._finalize_tool_synthesis(spoken_user, memory_block, on_thought)
            if reply:
                return _spoken_update(reply, used_tools=True, results=results)
    llm._trim()
    return _spoken_update(chunks[-1] if chunks else "", used_tools=used_tools, results=results)


def _search_fallback(question: str, search: str) -> str:
    if _user_wants_bullets(question):
        return _fallback_bullets_from_search(search)
    return _fallback_headlines_from_search(search)


def _force_needed_tool(
    llm: Any,
    spoken_user: str,
    on_tool: Callable[[str, Any], str],
    memory_block: str,
    on_thought: Callable[[str], None] | None,
) -> tuple[str, list[tuple[str, str]]] | None:
    if needs_current_time(spoken_user):
        try:
            result = on_tool("get_current_time", {})
        except Exception as exc:
            result = f"Error: tool 'get_current_time' failed: {exc}"
        llm.history.append({"role": "tool", "tool_name": "get_current_time", "content": result})
        reply = _format_time_tool_result(result)
        if reply:
            llm.history.append({"role": "assistant", "content": reply})
            return reply, [("get_current_time", result)]
        return None
    if needs_chat_context(spoken_user) and not _fresh_web_search(spoken_user):
        result = _invoke_conversation_log(on_tool)
        llm.history.append({"role": "tool", "tool_name": "conversation_log", "content": result})
        reply = llm._finalize_tool_synthesis(spoken_user, memory_block, on_thought)
        if reply:
            return reply, [("conversation_log", result)]
        return None
    if _fresh_web_search(spoken_user) or _is_web_search_followup(spoken_user, llm.history):
        result = _invoke_web_search(on_tool, spoken_user)
        llm.history.append({"role": "tool", "tool_name": "web_search", "content": result})
        reply = llm._finalize_tool_synthesis(spoken_user, memory_block, on_thought)
        if not reply:
            reply = _search_fallback(spoken_user, result)
            if reply:
                llm._append_internal_thought(
                    "Used a deterministic summary of the search results.",
                    on_thought,
                )
                llm.history.append({"role": "assistant", "content": reply})
        if reply:
            return reply, [("web_search", result)]
    if needs_prompt_files(spoken_user):
        try:
            catalog = on_tool("list_prompts", {})
        except Exception as exc:
            catalog = f"Error: tool 'list_prompts' failed: {exc}"
        llm.history.append({"role": "tool", "tool_name": "list_prompts", "content": catalog})
        if wants_prompt_reflection(spoken_user) or wants_prompt_catalog_list(spoken_user):
            paths = PROMPT_FILE_FOR_REFLECT if wants_prompt_reflection(spoken_user) else ()
            for path in paths:
                try:
                    content = on_tool("read_file", {"path": path})
                except Exception as exc:
                    content = f"Error: tool 'read_file' failed: {exc}"
                llm.history.append({"role": "tool", "tool_name": "read_file", "content": content})
            reply = llm._finalize_tool_synthesis(spoken_user, memory_block, on_thought)
            if reply:
                return reply, [("list_prompts", catalog)]
        system_text = ""
        if wants_verbatim_system_prompt(spoken_user):
            try:
                system_text = on_tool("read_file", {"path": "prompts/system.txt"})
            except Exception as exc:
                system_text = f"Error: tool 'read_file' failed: {exc}"
            llm.history.append({"role": "tool", "tool_name": "read_file", "content": system_text})
        reply = format_prompt_spoken_reply(spoken_user, catalog, system_text) or format_prompt_catalog_reply(catalog)
        if reply:
            llm.history.append({"role": "assistant", "content": reply})
            results = [("list_prompts", catalog)]
            if system_text:
                results.append(("read_file", system_text))
            return reply, results
    return None
