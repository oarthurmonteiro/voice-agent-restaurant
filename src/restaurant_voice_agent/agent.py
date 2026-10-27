import re
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, override

from restaurant_voice_agent.tools import Tool

MAX_CONSECUTIVE_TOOL_FAILURES = 2

DEFAULT_SYSTEM_PROMPT = """\
You are a friendly voice assistant for a restaurant. The customer is speaking \
to you out loud, not typing, so keep replies short, natural, and \
conversational, a sentence or two, never a list or a long paragraph.

Always answer in Brazilian Portuguese (pt-BR), regardless of the language of \
the question.

Use the available tools to answer questions you have a tool for (current \
time, opening hours, etc.) instead of guessing. Never invent information a \
tool could have given you.

Your reply is read aloud exactly as written by a text-to-speech engine that \
does not expand abbreviations, so never abbreviate times, numbers, or units. \
Spell them out in full the way you would say them out loud (say "oito \
horas", never "8h"; "vinte reais", never "R$20").

Stay focused on helping with the restaurant: hours, menu, orders, \
reservations. If asked something unrelated, briefly say you can't help with \
that and steer back.\
"""


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Message:
    role: MessageRole
    content: str
    tool_call_id: str | None = None  # set when role is TOOL, links back to the ToolCall.id it answers
    tool_call: ToolCall | None = None  # set when role is ASSISTANT and this turn is a tool request


@dataclass
class LLMResponse:
    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)

    @property
    def is_tool_call(self) -> bool:
        return len(self.tool_calls) > 0


class LLMAdapter(ABC):
    @abstractmethod
    def respond(self, history: list[Message], tools: list[dict[str, Any]], system: str) -> Iterator[LLMResponse]:
        ...


class LLMOllama(LLMAdapter):
    def __init__(self, model: str = "llama3.2"):
        self.model: str = model

    @override
    def respond(
        self,
        history: list[Message],
        tools: list[dict[str, Any]],
        system: str
    ) -> Iterator[LLMResponse]:
        import ollama

        messages = [{"role": "system", "content": system}]
        messages.extend(self._to_ollama_message(message) for message in history)
        ollama_tools = [self._to_ollama_tool(tool) for tool in tools]

        for chunk in ollama.chat(model=self.model, messages=messages, tools=ollama_tools, stream=True):
            message = chunk.message
            if message.tool_calls:
                calls = [
                    ToolCall(
                        id=call.function.name,
                        name=call.function.name,
                        arguments=dict(call.function.arguments)
                    )
                    for call in message.tool_calls
                ]
                yield LLMResponse(tool_calls=calls)
                return

            if message.content:
                yield LLMResponse(text=message.content)

    @staticmethod
    def _to_ollama_tool(tool: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool["parameters"],
            },
        }

    @staticmethod
    def _to_ollama_message(message: Message) -> dict[str, Any]:
        if message.role == MessageRole.TOOL:
            tool_name = message.tool_call_id
            return {"role": "tool", "content": message.content, "tool_name": tool_name}

        if message.role == MessageRole.ASSISTANT and message.tool_call is not None:
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"function": {"name": message.tool_call.name, "arguments": message.tool_call.arguments}}
                ],
            }

        return {"role": message.role.value, "content": message.content}


_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s*")

class Agent:
    def __init__(self, model: LLMAdapter, tools: dict[str, Tool], system_prompt: str = DEFAULT_SYSTEM_PROMPT):
        self.model: LLMAdapter = model
        self.tools: dict[str, Tool] = tools
        self.tool_schemas: list[dict[str, Any]] = [tool.to_schema() for tool in tools.values()]
        self.system_prompt: str = system_prompt
        self.history: list[Message] = []

    # def run(self, user_text: str, stream: bool = False) -> str | Iterator[str]:
    #    sentences = self._run_stream(user_text)
    #    return sentences if stream else "".join(sentences)

    def run(self, user_text: str) -> Iterator[str]:
        self.history.append(Message(role=MessageRole.USER, content=user_text))

        consecutive_failures = 0
        while True:
            buffer = ""
            full_text = ""
            tool_calls: list[ToolCall] = []

            for piece in self.model.respond(self.history, self.tool_schemas, self.system_prompt):
                if piece.is_tool_call:
                    tool_calls = piece.tool_calls
                    break

                full_text += piece.text or ""
                buffer += piece.text or ""
                sentences, buffer = self._split_sentences(buffer)
                yield from sentences

            if tool_calls:
                if self._run_tools(tool_calls):
                    consecutive_failures = 0
                    continue

                consecutive_failures += 1
                if consecutive_failures >= MAX_CONSECUTIVE_TOOL_FAILURES:
                    fallback = "Sorry, I'm having trouble with that right now."
                    self.history.append(Message(role=MessageRole.ASSISTANT, content=fallback))
                    yield fallback
                    return
                continue

            if buffer:
                yield buffer

            self.history.append(Message(role=MessageRole.ASSISTANT, content=full_text))
            return

    @staticmethod
    def _split_sentences(buffer: str) -> tuple[list[str], str]:
        *complete, remainder = _SENTENCE_BOUNDARY.split(buffer)
        return [s for s in complete if s], remainder

    def _run_tools(self, calls: list[ToolCall]) -> bool:
        # Must be a list, not a generator: any() short-circuits on the first True,
        # which would skip calling (and executing) every tool after the first success.
        return any([self._run_tool(call) for call in calls])  # noqa: C419

    def _run_tool(self, call: ToolCall) -> bool:
        print(f"[agent] tool call: {call.name}({call.arguments})")
        self.history.append(Message(role=MessageRole.ASSISTANT, content="", tool_call=call))
        result, failed = self._validate_and_invoke(call)
        print(f"[agent] tool result ({'failed' if failed else 'ok'}): {result}")
        self.history.append(Message(role=MessageRole.TOOL, content=result, tool_call_id=call.id))
        return not failed

    def _validate_and_invoke(self, call: ToolCall) -> tuple[str, bool]:
        tool = self.tools.get(call.name)
        if tool is None:
            return f"error: unknown tool '{call.name}'", True

        missing = [key for key in tool.parameters.get("required", []) if key not in call.arguments]
        if missing:
            return f"error: missing required arguments: {', '.join(missing)}", True

        try:
            return tool.invoke(**call.arguments), False
        except Exception as exc:  # noqa: BLE001 - any tool failure is a recoverable turn failure, not a crash
            return f"error: tool failed: {exc}", True
