"""Deterministic LLM cassettes for fast, network-free test runs."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import ConfigDict, PrivateAttr

CASSETTE_DIR = Path(__file__).parent / "cassettes"


def _serialize(message: AIMessage) -> dict:
    return {"content": message.content, "tool_calls": message.tool_calls or []}


def _deserialize(data: dict) -> AIMessage:
    return AIMessage(content=data["content"], tool_calls=data["tool_calls"])


class CassetteChatModel(BaseChatModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    path: Path
    mode: str = "replay"
    underlying: Any = None  # a real BaseChatModel, required for mode="record"

    _recorded: list[dict] = PrivateAttr(default_factory=list)
    _replay_queue: list[AIMessage] = PrivateAttr(default_factory=list)

    def model_post_init(self, context: Any, /) -> None:
        if self.mode == "replay":
            if not self.path.exists():
                raise FileNotFoundError(f"no cassette recorded at {self.path} -- run record_cassettes.py first")
            self._replay_queue = [_deserialize(m) for m in json.loads(self.path.read_text())]
        elif self.mode != "record":
            raise ValueError(f"mode must be 'record' or 'replay', got {self.mode!r}")
        elif self.underlying is None:
            raise ValueError("mode='record' requires `underlying` (a real chat model)")

    def bind_tools(self, tools, **kwargs):
        if self.underlying is not None:
            self.underlying = self.underlying.bind_tools(tools, **kwargs)
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        if self.mode == "record":
            result = self.underlying.invoke(messages, stop=stop, **kwargs)
            ai_message = result if isinstance(result, AIMessage) else result.generations[0].message
            self._recorded.append(_serialize(ai_message))
            return ChatResult(generations=[ChatGeneration(message=ai_message)])

        if not self._replay_queue:
            raise AssertionError(
                f"cassette {self.path} ran out of recorded responses -- the graph's control "
                "flow diverged from the recording (a different model, prompt, or tool set "
                "than when this cassette was made). Re-run record_cassettes.py."
            )
        return ChatResult(generations=[ChatGeneration(message=self._replay_queue.pop(0))])

    def save(self) -> None:
        if self.mode != "record":
            raise RuntimeError("save() only makes sense in mode='record'")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._recorded, indent=2))

    @property
    def recorded_count(self) -> int:
        return len(self._recorded)

    @property
    def _llm_type(self) -> str:
        return "cassette"
