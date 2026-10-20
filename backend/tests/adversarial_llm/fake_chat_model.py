"""A fully-scripted fake chat model for deterministic graph tests."""
from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class ScriptedChatModel(BaseChatModel):
    responses: list[AIMessage]

    def bind_tools(self, tools, **kwargs):
        return self  # fully scripted, tool schemas aren't consulted

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        if not self.responses:
            raise AssertionError("ScriptedChatModel ran out of scripted responses")
        message = self.responses.pop(0)
        return ChatResult(generations=[ChatGeneration(message=message)])

    @property
    def _llm_type(self) -> str:
        return "scripted-fake"


class LoopingChatModel(BaseChatModel):
    call_count: int = 0

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.call_count += 1
        if kwargs.get("tool_choice") == "none":
            message = final_message(f"Best answer after {self.call_count - 1} tool calls.")
        else:
            message = tool_call_message(
                "get_current_param", {"name": f"PARAM_{self.call_count}"}, f"call_{self.call_count}",
            )
        return ChatResult(generations=[ChatGeneration(message=message)])

    @property
    def _llm_type(self) -> str:
        return "looping-fake"


def tool_call_message(name: str, args: dict, call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}])


def final_message(content: str) -> AIMessage:
    return AIMessage(content=content)


class StubbornLoopingChatModel(LoopingChatModel):
    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        kwargs.pop("tool_choice", None)
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


class ToolsIgnoreNoneChoiceChatModel(BaseChatModel):
    tools_bound: bool = False
    calls: int = 0

    def bind_tools(self, tools, **kwargs):
        return self.model_copy(update={"tools_bound": True})

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        if self.tools_bound:
            message = tool_call_message("get_current_param", {"name": f"PARAM_{len(messages)}"}, f"call_{len(messages)}")
        else:
            message = final_message("Summary from what I found: the compass is not calibrated.")
        return ChatResult(generations=[ChatGeneration(message=message)])

    @property
    def _llm_type(self) -> str:
        return "tools-ignore-none-choice"

