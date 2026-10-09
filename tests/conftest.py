"""Shared fixtures. Tests run without root, GPU, Ollama, or network."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from adversarial_poetry.config import Config  # noqa: E402

# Unix primitives the security tests depend on.
UNIX = hasattr(os, "fork") and hasattr(os, "O_NOFOLLOW")
requires_unix = pytest.mark.skipif(not UNIX, reason="requires Unix (fork/O_NOFOLLOW)")


class FakeOllamaClient:
    """Deterministic stand-in for the real HTTP client.

    Records the options passed to each ``generate`` call so tests can assert on
    seeds/temperature, and returns a predictable poem.
    """

    def __init__(self, response: str = "line one\nline two") -> None:
        self.response = response
        self.calls: list[dict] = []
        self.models = ["fake-writer:latest"]

    def list_models(self) -> list[str]:
        return list(self.models)

    def generate(self, model, prompt, *, system=None, options=None) -> str:
        self.calls.append(
            {"model": model, "prompt": prompt, "system": system, "options": options or {}}
        )
        return self.response

    def chat(self, model, messages, *, tools=None, options=None) -> dict:
        return {"role": "assistant", "content": "ok"}


@pytest.fixture
def allowed_root(tmp_path: Path) -> Path:
    root = tmp_path / "Poetry" / "arena drafts"  # space on purpose
    root.mkdir(parents=True)
    # Canonicalise so symlinked tmp roots (e.g. macOS /var) don't trip is_within.
    return Path(os.path.realpath(root))


@pytest.fixture
def config(allowed_root: Path) -> Config:
    return Config(
        ollama_endpoint="http://127.0.0.1:11434",
        writer_models=("fake-writer:latest",),
        default_model="fake-writer:latest",
        default_form="free_verse",
        temperature=0.5,
        seed=None,
        allowed_output_roots=(allowed_root,),
    )


@pytest.fixture
def fake_client() -> FakeOllamaClient:
    return FakeOllamaClient()
