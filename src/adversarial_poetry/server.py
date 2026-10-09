"""MCP stdio server exposing the writer-only poem generation service.

Transport: stdio. JSON-RPC protocol messages go to **stdout**; all diagnostics
and logging go to **stderr**. The server exposes only *writer* tools: listing
forms/models, generating poems, and saving them to allowed output roots. It
never submits, tests, scores, or transmits generated artifacts.

Run directly (normally launched by the terminal client):

    adversarial-poetry-server [--config PATH] [--output-root DIR ...]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

from .config import Config, load_config
from .errors import EXIT_CONFIG, AdversarialPoetryError
from .forms import FORMS, list_forms
from .generation import GenerationService, PoemRequest
from .ollama_client import OllamaClient
from .paths import resolve_output_path
from .safeio import write_batch

log = logging.getLogger("adversarial_poetry.server")


def _configure_logging() -> None:
    # Diagnostics strictly on stderr so stdout stays a clean JSON-RPC channel.
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger("adversarial_poetry")
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)


def build_server(config: Config):
    """Construct the FastMCP server with tools bound to ``config``."""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("adversarial-poetry")
    client = OllamaClient(config.ollama_endpoint, timeout=config.request_timeout)
    service = GenerationService(client, config)

    @mcp.tool()
    def list_poetic_forms() -> list[dict[str, str]]:
        """List the available English poetic forms and a short description."""
        return [{"name": n, "summary": FORMS[n].summary} for n in list_forms()]

    @mcp.tool()
    def list_models() -> dict[str, Any]:
        """List locally installed Ollama models available as writer models."""
        try:
            return {"models": client.list_models()}
        except AdversarialPoetryError as exc:
            return {"error": str(exc)}

    @mcp.tool()
    def generate_poems(
        brief: str,
        form: str = config.default_form,
        count: int = 1,
        model: str | None = None,
        temperature: float | None = None,
        seed: int | None = None,
        title: str | None = None,
    ) -> dict[str, Any]:
        """Generate one or more poems on ``brief`` in ``form``. Does not save.

        Returns the poem texts. Use ``save_poems`` to persist them, or
        ``generate_and_save`` to do both in one call.
        """
        try:
            req = PoemRequest(
                brief=brief, form=form, count=count, model=model,
                temperature=temperature, seed=seed, title=title,
            )
            poems = service.generate_batch(req)
            return {"poems": poems, "count": len(poems)}
        except AdversarialPoetryError as exc:
            return {"error": str(exc)}

    @mcp.tool()
    def save_poems(
        poems: list[str],
        output_path: str,
        mode: str = "append",
    ) -> dict[str, Any]:
        """Save poems to ``output_path`` (append by default, or exclusive create).

        The path must resolve inside a configured allowed output root. Existing
        files are never silently overwritten; symlinks and non-regular targets
        are refused.
        """
        try:
            target = resolve_output_path(output_path, config.default_output_root)
            written = write_batch(
                poems, target, config.allowed_output_roots, mode=mode
            )
            return {"path": str(target), "bytes_written": written, "poems": len(poems)}
        except AdversarialPoetryError as exc:
            return {"error": str(exc)}
        except ValueError as exc:
            return {"error": str(exc)}

    @mcp.tool()
    def generate_and_save(
        brief: str,
        output_path: str,
        form: str = config.default_form,
        count: int = 1,
        mode: str = "append",
        model: str | None = None,
        temperature: float | None = None,
        seed: int | None = None,
        title: str | None = None,
    ) -> dict[str, Any]:
        """Generate poems and save them to ``output_path`` in one step."""
        try:
            req = PoemRequest(
                brief=brief, form=form, count=count, model=model,
                temperature=temperature, seed=seed, title=title,
            )
            poems = service.generate_batch(req)
            target = resolve_output_path(output_path, config.default_output_root)
            written = write_batch(
                poems, target, config.allowed_output_roots, mode=mode
            )
            return {
                "path": str(target),
                "bytes_written": written,
                "poems": len(poems),
            }
        except AdversarialPoetryError as exc:
            return {"error": str(exc)}
        except ValueError as exc:
            return {"error": str(exc)}

    return mcp


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="adversarial-poetry-server",
        description="MCP stdio server for writer-only adversarial-poetry generation.",
    )
    p.add_argument("--config", help="explicit path to a config.toml")
    p.add_argument(
        "--output-root", action="append", dest="output_roots", metavar="DIR",
        help="additional allowed output root (may be repeated)",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    args = _parse_args(argv)
    try:
        config = load_config(args.config, extra_roots=args.output_roots)
    except AdversarialPoetryError as exc:
        log.error("configuration error: %s", exc)
        return EXIT_CONFIG

    roots = ", ".join(str(r) for r in config.allowed_output_roots) or "(none)"
    log.info("endpoint=%s allowed_roots=%s", config.ollama_endpoint, roots)

    server = build_server(config)
    # FastMCP.run() drives the stdio transport until stdin closes (EOF) or the
    # process is signalled; it keeps JSON-RPC on stdout.
    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
