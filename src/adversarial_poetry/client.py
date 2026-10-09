"""Ollama-orchestrated terminal MCP client.

Launches the MCP server as a subprocess over stdio (explicit executable and
argument list -- never a shell string, never ``shell=True``), exposes the
server's writer tools to a local Ollama model, and runs an interactive loop in
which the model may call those tools to generate and save poems.

The subprocess is launched with the *current* interpreter (``sys.executable``),
i.e. the active virtual environment, running ``-m adversarial_poetry.server``.
This guarantees client and server share one environment. Termination, EOF, and
SIGINT/SIGTERM all unwind cleanly and tear the subprocess down.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import sys
from typing import Any

from .config import load_config
from .errors import (
    EXIT_CONFIG,
    EXIT_CONNECTION,
    EXIT_INTERRUPTED,
    EXIT_OK,
    AdversarialPoetryError,
)

log = logging.getLogger("adversarial_poetry.client")

ORCHESTRATION_SYSTEM = (
    "You orchestrate a writer-only poetry tool via function calls. Use the "
    "provided tools to list forms/models and to generate and save poems to the "
    "user's chosen file. You only write poems; you never submit, test, or send "
    "them anywhere. Prefer generate_and_save when the user wants poems written "
    "to a file. Always report the saved path back to the user."
)


def _server_argv(config_path: str | None, output_roots: list[str] | None) -> list[str]:
    argv = [sys.executable, "-m", "adversarial_poetry.server"]
    if config_path:
        argv += ["--config", config_path]
    for root in output_roots or []:
        argv += ["--output-root", root]
    return argv


def _mcp_tools_to_ollama(tools: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for t in tools:
        out.append(
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": (t.description or "").strip(),
                    "parameters": t.inputSchema or {"type": "object", "properties": {}},
                },
            }
        )
    return out


def _tool_result_text(result: Any) -> str:
    """Flatten an MCP call_tool result into text for the model."""
    chunks: list[str] = []
    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        if text is not None:
            chunks.append(text)
    return "\n".join(chunks) if chunks else "(no content)"


async def _run(args: argparse.Namespace) -> int:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    from .ollama_client import OllamaClient

    config = load_config(args.config, extra_roots=args.output_roots)
    model = args.model or config.default_model
    if not model:
        log.error(
            "no orchestration model: pass --model or set default_model in config"
        )
        return EXIT_CONFIG

    ollama = OllamaClient(config.ollama_endpoint, timeout=config.request_timeout)

    server_params = StdioServerParameters(
        command=sys.executable,
        args=_server_argv(args.config, args.output_roots)[1:],
        env=None,
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, ValueError):
            pass

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            tools = _mcp_tools_to_ollama(listed.tools)
            log.info("connected; %d tools available", len(tools))

            messages: list[dict[str, Any]] = [
                {"role": "system", "content": ORCHESTRATION_SYSTEM}
            ]
            print(
                "adversarial-poetry client ready. Describe the poems you want "
                "(Ctrl+D or Ctrl+C to quit).",
                file=sys.stderr,
            )

            while not stop.is_set():
                try:
                    user = await asyncio.to_thread(input, "poet> ")
                except (EOFError, KeyboardInterrupt):
                    break
                if stop.is_set():
                    break
                user = user.strip()
                if not user:
                    continue
                if user in ("/quit", "/exit"):
                    break

                messages.append({"role": "user", "content": user})

                # Tool-calling loop: let the model call tools until it answers.
                for _ in range(16):
                    if stop.is_set():
                        break
                    try:
                        msg = await asyncio.to_thread(
                            ollama.chat, model, messages, tools=tools
                        )
                    except AdversarialPoetryError as exc:
                        print(f"error: {exc}", file=sys.stderr)
                        break

                    messages.append(msg)
                    tool_calls = msg.get("tool_calls") or []
                    if not tool_calls:
                        content = (msg.get("content") or "").strip()
                        if content:
                            print(content)
                        break

                    for call in tool_calls:
                        fn = call.get("function", {})
                        name = fn.get("name", "")
                        raw_args = fn.get("arguments", {})
                        if isinstance(raw_args, str):
                            try:
                                raw_args = json.loads(raw_args)
                            except ValueError:
                                raw_args = {}
                        log.info("tool call: %s", name)
                        try:
                            result = await session.call_tool(name, raw_args)
                            text = _tool_result_text(result)
                        except Exception as exc:  # noqa: BLE001 - surface to model
                            text = f"tool error: {exc}"
                        messages.append(
                            {"role": "tool", "name": name, "content": text}
                        )

    return EXIT_INTERRUPTED if stop.is_set() else EXIT_OK


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="adversarial-poetry-client",
        description="Ollama-orchestrated terminal MCP client for poem generation.",
    )
    p.add_argument("--config", help="explicit path to a config.toml")
    p.add_argument("--model", help="Ollama model used to orchestrate tool calls")
    p.add_argument(
        "--output-root", action="append", dest="output_roots", metavar="DIR",
        help="additional allowed output root (may be repeated)",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger("adversarial_poetry")
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)

    args = _parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        return EXIT_INTERRUPTED
    except AdversarialPoetryError as exc:
        log.error("%s", exc)
        return getattr(exc, "exit_code", EXIT_CONNECTION)


if __name__ == "__main__":
    raise SystemExit(main())
