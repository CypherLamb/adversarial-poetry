"""Minimal Ollama HTTP client built on the standard library.

Only the local, configured endpoint is contacted. There is no cloud fallback
and no third-party HTTP dependency. Blocking network calls honour the configured
timeout; a SIGINT during a request interrupts the underlying socket read.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from .errors import ConnectionFailure


class OllamaClient:
    def __init__(self, endpoint: str, timeout: float = 120.0) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout

    # -- low-level ----------------------------------------------------------
    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.endpoint}{path}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, method="POST",
            headers={"Content-Type": "application/json"},
        )
        return self._send(req)

    def _get(self, path: str) -> dict[str, Any]:
        req = urllib.request.Request(f"{self.endpoint}{path}", method="GET")
        return self._send(req)

    def _send(self, req: urllib.request.Request) -> dict[str, Any]:
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace") if exc.fp else ""
            raise ConnectionFailure(
                f"Ollama returned HTTP {exc.code} for {req.full_url}: {detail.strip()}"
            ) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise ConnectionFailure(
                f"cannot reach Ollama at {self.endpoint}: {exc}. Is `ollama serve` "
                f"running and the endpoint correct?"
            ) from exc
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ConnectionFailure(f"invalid JSON from Ollama: {exc}") from exc

    # -- public API ---------------------------------------------------------
    def list_models(self) -> list[str]:
        """Return the names of locally installed models (``GET /api/tags``)."""
        data = self._get("/api/tags")
        models = data.get("models") or []
        return [m.get("name", "") for m in models if m.get("name")]

    def generate(
        self,
        model: str,
        prompt: str,
        *,
        system: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> str:
        """Non-streaming ``POST /api/generate``; returns the response text."""
        payload: dict[str, Any] = {"model": model, "prompt": prompt, "stream": False}
        if system:
            payload["system"] = system
        if options:
            payload["options"] = options
        data = self._post("/api/generate", payload)
        return str(data.get("response", ""))

    def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Non-streaming ``POST /api/chat``; returns the assistant message dict.

        Used by the orchestration client for tool-calling. The returned dict is
        the ``message`` object, which may contain ``tool_calls``.
        """
        payload: dict[str, Any] = {"model": model, "messages": messages, "stream": False}
        if tools:
            payload["tools"] = tools
        if options:
            payload["options"] = options
        data = self._post("/api/chat", payload)
        return data.get("message", {}) or {}
