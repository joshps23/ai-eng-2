"""LLMClient: thin wrapper around client.responses.create with retry logic."""
from __future__ import annotations

import time
from typing import Any

# We import openai lazily so that the module can be imported even if the
# package is only partially installed (e.g., tests with FakeClient).
try:
    from openai import (
        RateLimitError,
        APIConnectionError,
        InternalServerError,
        OpenAI,
    )
    _OPENAI_AVAILABLE = True
except ImportError:  # pragma: no cover
    _OPENAI_AVAILABLE = False

    class RateLimitError(Exception): pass  # type: ignore[no-redef]
    class APIConnectionError(Exception): pass  # type: ignore[no-redef]
    class InternalServerError(Exception): pass  # type: ignore[no-redef]


_RETRYABLE = (RateLimitError, APIConnectionError, InternalServerError)
_MAX_RETRIES = 5
_BASE_DELAY = 1.0  # seconds


class LLMClient:
    """Wraps responses.create with exponential back-off retry.

    Accepts an injected ``client`` so tests can pass a FakeClient without
    hitting the real API.
    """

    def __init__(self, client: Any | None = None, model: str = "gpt-4o") -> None:
        if client is not None:
            self._client = client
        elif _OPENAI_AVAILABLE:
            self._client = OpenAI()
        else:  # pragma: no cover
            raise RuntimeError("openai package not available and no client injected")
        self.model = model

    def create(
        self,
        instructions: str,
        input: list[dict],
        tools: list[dict] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Call responses.create with retry/backoff.

        Returns the raw response object (real or fake).
        """
        tools = tools or []
        attempt = 0
        delay = _BASE_DELAY
        last_exc: Exception | None = None

        while attempt < _MAX_RETRIES:
            try:
                return self._client.responses.create(
                    model=self.model,
                    instructions=instructions,
                    input=input,
                    tools=tools,
                    **kwargs,
                )
            except _RETRYABLE as exc:  # type: ignore[misc]
                last_exc = exc
                attempt += 1
                if attempt >= _MAX_RETRIES:
                    break
                time.sleep(delay)
                delay = min(delay * 2, 60.0)
            except Exception:
                raise

        raise last_exc  # type: ignore[misc]
