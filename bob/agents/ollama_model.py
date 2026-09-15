from __future__ import annotations

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import ConfigDict, PrivateAttr


def langchain_to_ollama(messages: list[BaseMessage]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for msg in messages:
        if isinstance(msg, SystemMessage):
            out.append({"role": "system", "content": str(msg.content or "")})
        elif isinstance(msg, HumanMessage):
            out.append({"role": "user", "content": str(msg.content or "")})
        elif isinstance(msg, ToolMessage):
            out.append(
                {
                    "role": "tool",
                    "tool_name": str(getattr(msg, "name", "") or ""),
                    "content": str(msg.content or ""),
                }
            )
        elif isinstance(msg, AIMessage):
            item: dict[str, Any] = {"role": "assistant", "content": str(msg.content or "")}
            tool_calls = getattr(msg, "tool_calls", None)
            if tool_calls:
                item["tool_calls"] = list(tool_calls)
            out.append(item)
        else:
            role = str(getattr(msg, "type", "user") or "user")
            if role == "ai":
                role = "assistant"
            elif role == "human":
                role = "user"
            out.append({"role": role, "content": str(getattr(msg, "content", "") or "")})
    return out


class BobOllamaChat(BaseChatModel):
    """LangChain chat model that reuses BOB's Ollama HTTP client and think-gate."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    _llm: Any = PrivateAttr()

    def __init__(self, llm: Any, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._llm = llm

    @property
    def _llm_type(self) -> str:
        return "bob-ollama"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        payload = langchain_to_ollama(list(messages))
        content, thinking, _meta = self._llm._post_chat(
            payload,
            num_predict=int(kwargs.get("num_predict") or 256),
            temperature=float(kwargs.get("temperature") or 0.2),
            think=bool(kwargs.get("think", False)),
        )
        message = AIMessage(content=content or "")
        if thinking:
            message.additional_kwargs["thinking"] = thinking
        return ChatResult(generations=[ChatGeneration(message=message)])

    def generate_text(self, instruction: str, user_text: str, num_predict: int = 256) -> str:
        return str(self._llm.generate(instruction, user_text, num_predict) or "")
