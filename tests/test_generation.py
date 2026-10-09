"""Generation-service tests using a fake Ollama client (no network)."""

from __future__ import annotations

import threading

import pytest

from adversarial_poetry.errors import Cancelled, GenerationError
from adversarial_poetry.generation import GenerationService, PoemRequest, _extract_poem


def test_batch_count_and_seed_determinism(config, fake_client):
    svc = GenerationService(fake_client, config)
    req = PoemRequest(brief="the sea", form="free_verse", count=3, seed=100)
    poems = svc.generate_batch(req)
    assert len(poems) == 3
    seeds = [c["options"]["seed"] for c in fake_client.calls]
    assert seeds == [100, 101, 102]
    # Temperature falls back to the config value when unset on the request.
    assert all(c["options"]["temperature"] == 0.5 for c in fake_client.calls)


def test_request_temperature_overrides_config(config, fake_client):
    svc = GenerationService(fake_client, config)
    req = PoemRequest(brief="x", form="haiku", count=1, temperature=0.1)
    svc.generate_batch(req)
    assert fake_client.calls[0]["options"]["temperature"] == 0.1


def test_system_prompt_is_writer_only(config, fake_client):
    svc = GenerationService(fake_client, config)
    svc.generate_one("x", "haiku")
    system = fake_client.calls[0]["system"]
    assert "ONLY the poem" in system


def test_extract_poem_strips_code_fence():
    assert _extract_poem("```\nrose and thorn\n```") == "rose and thorn"
    assert _extract_poem("```text\na\nb\n```") == "a\nb"
    assert _extract_poem("  plain poem  ") == "plain poem"


def test_empty_response_is_error(config):
    from conftest import FakeOllamaClient

    svc = GenerationService(FakeOllamaClient(response=""), config)
    with pytest.raises(GenerationError):
        svc.generate_one("x", "haiku")


def test_cancel_before_start_raises(config, fake_client):
    svc = GenerationService(fake_client, config)
    cancel = threading.Event()
    cancel.set()
    req = PoemRequest(brief="x", form="haiku", count=3)
    with pytest.raises(Cancelled):
        svc.generate_batch(req, cancel=cancel)


def test_cancel_mid_batch_returns_partial(config, fake_client):
    svc = GenerationService(fake_client, config)
    cancel = threading.Event()

    def progress(done, total, poem):
        if done == 1:
            cancel.set()  # cancel after the first poem

    req = PoemRequest(brief="x", form="haiku", count=5)
    poems = svc.generate_batch(req, cancel=cancel, on_progress=progress)
    assert len(poems) == 1
