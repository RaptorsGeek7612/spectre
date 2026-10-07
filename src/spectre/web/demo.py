"""Demo mode: canned, streamed answers so the web UI runs with no API key and no network.

Texts live in `static/demo.json`, shared with the browser-only showcase. The final text is a real
Spectre output (2026-10-07); the draft is an illustrative earlier version with the slips Warden
corrects, so the "Corrections" view has something to show. The UI labels all of it as a demo.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from importlib.resources import files
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

_DATA: dict[str, Any] = json.loads(
    (files("spectre.web") / "static" / "demo.json").read_text(encoding="utf-8")
)
DEMO_REQUEST: str = _DATA["request"]
_BRIEF: str = _DATA["brief"]
_FINAL: str = _DATA["final"]
# Illustrative earlier draft: Warden corrects these slips in the final text.
_DRAFT = _FINAL
for _right, _wrong in _DATA["draft_slips"]:
    _DRAFT = _DRAFT.replace(_right, _wrong)


def demo_text(agent: str, request: str) -> str:
    """Canned answer of `agent` for `request`."""
    if agent == "scout":
        return _BRIEF.format(request=request.strip() or DEMO_REQUEST)
    if agent == "scribe":
        return _DRAFT
    return _FINAL


def _rough_tokens(text: str) -> int:
    """Token estimate for demo usage figures (about 4 characters per token)."""
    return max(1, len(text) // 4)


class DemoChatModel(BaseChatModel):
    """Streams the canned answer of `agent` word by word, `delay` seconds apart."""

    agent: str
    model: str
    delay: float = 0.0

    @property
    def _llm_type(self) -> str:
        return "spectre-demo"

    def _answer(self, messages: list[BaseMessage]) -> tuple[str, int]:
        prompt = "\n".join(str(message.content) for message in messages)
        request = DEMO_REQUEST
        if self.agent == "scout" and messages:
            request = str(messages[-1].content)
        return demo_text(self.agent, request), _rough_tokens(prompt)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        text, input_tokens = self._answer(messages)
        output_tokens = _rough_tokens(text)
        message = AIMessage(
            content=text,
            response_metadata={"stop_reason": "end_turn", "model_name": self.model},
            usage_metadata={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
            },
        )
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        text, input_tokens = self._answer(messages)
        words = text.split(" ")
        for index, word in enumerate(words):
            piece = word if index == 0 else " " + word
            # langchain-core reports each yielded chunk to the callbacks (LangGraph streaming).
            yield ChatGenerationChunk(message=AIMessageChunk(content=piece))
            if self.delay:
                time.sleep(self.delay)
        output_tokens = _rough_tokens(text)
        yield ChatGenerationChunk(
            message=AIMessageChunk(
                content="",
                response_metadata={"stop_reason": "end_turn", "model_name": self.model},
                usage_metadata={
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": input_tokens + output_tokens,
                },
            )
        )
