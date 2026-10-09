"""The shared generation service used by the server, client, and CLI.

This is the single place poems are produced. The MCP server and the
deterministic CLI both call it, guaranteeing identical generation behaviour
whether or not a model is orchestrating tool calls.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable

from . import forms
from .config import Config
from .errors import Cancelled, GenerationError
from .ollama_client import OllamaClient


@dataclass(frozen=True)
class PoemRequest:
    brief: str
    form: str
    count: int = 1
    model: str | None = None
    temperature: float | None = None
    seed: int | None = None
    title: str | None = None


def _extract_poem(text: str) -> str:
    """Return poem-only text.

    The writer-only system prompt does most of the work; here we defensively
    strip a wrapping markdown code fence and surrounding whitespace, which some
    models add despite instructions. We do not try to second-guess the body.
    """
    s = text.strip()
    if s.startswith("```"):
        lines = s.splitlines()
        # drop opening fence (possibly ```text / ```poem)
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        s = "\n".join(lines).strip()
    return s


class GenerationService:
    def __init__(self, client: OllamaClient, config: Config) -> None:
        self.client = client
        self.config = config

    def _options(self, temperature: float | None, seed: int | None) -> dict[str, Any]:
        opts: dict[str, Any] = {}
        temp = self.config.temperature if temperature is None else temperature
        opts["temperature"] = float(temp)
        s = self.config.seed if seed is None else seed
        if s is not None:
            opts["seed"] = int(s)
        return opts

    def generate_one(
        self,
        brief: str,
        form: str,
        *,
        model: str | None = None,
        temperature: float | None = None,
        seed: int | None = None,
        title: str | None = None,
    ) -> str:
        resolved_model = self.config.resolved_model(model)
        prompt = forms.build_prompt(form, brief, title=title)
        raw = self.client.generate(
            resolved_model,
            prompt,
            system=forms.SYSTEM_PROMPT,
            options=self._options(temperature, seed),
        )
        poem = _extract_poem(raw)
        if not poem:
            raise GenerationError("model returned an empty poem")
        return poem

    def generate_batch(
        self,
        request: PoemRequest,
        *,
        cancel: threading.Event | None = None,
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> list[str]:
        """Generate ``request.count`` poems.

        Batch generation is *repeatable*: when a ``seed`` is set, poem ``i`` uses
        ``seed + i`` so the whole batch is deterministic across runs while the
        individual poems still differ. Without a seed, generation is left to the
        model's own randomness.

        ``cancel`` is checked between poems; when set, already-generated poems
        are returned and a :class:`Cancelled` is raised only if nothing was
        produced. ``on_progress(done, total, poem)`` is called after each poem.
        """
        if request.count < 1:
            raise ValueError("count must be >= 1")

        poems: list[str] = []
        base_seed = self.config.seed if request.seed is None else request.seed
        total = request.count
        for i in range(total):
            if cancel is not None and cancel.is_set():
                break
            seed_i = None if base_seed is None else int(base_seed) + i
            try:
                poem = self.generate_one(
                    request.brief,
                    request.form,
                    model=request.model,
                    temperature=request.temperature,
                    seed=seed_i,
                    title=request.title,
                )
            except GenerationError:
                # Preserve what we have; signal partial failure if some succeeded.
                if poems:
                    raise GenerationError(
                        f"generated {len(poems)} of {total} poems before a failure"
                    )
                raise
            poems.append(poem)
            if on_progress is not None:
                on_progress(i + 1, total, poem)

        if not poems:
            if cancel is not None and cancel.is_set():
                raise Cancelled("generation cancelled before any poem completed")
            raise GenerationError("no poems were generated")
        return poems
