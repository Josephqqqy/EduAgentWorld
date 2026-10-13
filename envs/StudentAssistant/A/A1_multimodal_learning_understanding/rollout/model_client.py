"""One-turn OpenAI-compatible chat client, independent of the agent loop."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import ModelConfig


class ModelClientError(RuntimeError):
    """The model response cannot be used by the agent loop."""

    def __init__(self, message, *, category="unknown", details=None):
        super().__init__(message)
        self.category = category
        self.details = details or {}


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ModelResponse:
    message: dict[str, Any]
    content: str | None
    tool_calls: tuple[ToolCall, ...]
    finish_reason: str | None
    usage: dict[str, Any]
    model: str | None
    request_id: str | None
    latency_ms: float


class ModelClient:
    def __init__(
        self,
        config: ModelConfig,
        *,
        transport: Callable[..., Any] = urlopen,
        sleep: Callable[[float], None] = time.sleep,
        max_retries: int = 2,
    ):
        self.config = config
        self.transport = transport
        self.sleep = sleep
        if max_retries < 0:
            raise ValueError("max_retries must be nonnegative")
        self.max_retries = max_retries

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> ModelResponse:
        """Return a parsed reply with a replayable assistant message."""
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if tools is not None:
            payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice

        request = Request(
            f"{self.config.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        start = time.perf_counter()
        for attempt in range(self.max_retries + 1):
            try:
                with self.transport(request, timeout=self.config.timeout) as response:
                    data = json.load(response)
                break
            except HTTPError as error:
                if error.code in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                    self.sleep(0.5 * 2**attempt)
                    continue
                raise ModelClientError(
                    f"Model API HTTP {error.code}",
                    category="http",
                    details={"status_code": error.code},
                ) from None
            except (URLError, TimeoutError, OSError) as error:
                raise ModelClientError(
                    f"Model API connection failed: {type(error).__name__}",
                    category="connection",
                    details={"exception_type": type(error).__name__},
                ) from None
            except (ValueError, UnicodeError):
                raise ModelClientError(
                    "Model API returned invalid JSON",
                    category="invalid_json",
                ) from None

        try:
            choice = data["choices"][0]
            raw_message = choice["message"]
            if not isinstance(raw_message, dict):
                raise ValueError("assistant message must be an object")
            calls = []
            for call in raw_message.get("tool_calls") or []:
                arguments = json.loads(call["function"]["arguments"])
                if not isinstance(arguments, dict):
                    raise ValueError("tool arguments must be an object")
                calls.append(
                    ToolCall(
                        id=call["id"],
                        name=call["function"]["name"],
                        arguments=arguments,
                    )
                )
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise ModelClientError(
                f"Invalid model response or tool arguments: {type(error).__name__}",
                category="invalid_response",
                details={"exception_type": type(error).__name__},
            ) from None

        message = {"role": "assistant", "content": raw_message.get("content")}
        if raw_message.get("tool_calls"):
            message["tool_calls"] = raw_message["tool_calls"]

        return ModelResponse(
            message=message,
            content=message.get("content"),
            tool_calls=tuple(calls),
            finish_reason=choice.get("finish_reason"),
            usage=data.get("usage") or {},
            model=data.get("model"),
            request_id=data.get("id"),
            latency_ms=(time.perf_counter() - start) * 1000,
        )
