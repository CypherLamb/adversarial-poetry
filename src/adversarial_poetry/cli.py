"""Deterministic local CLI.

Uses the same :class:`GenerationService` as the MCP server but drives it
directly, without any model tool-calling. Output is script-friendly: results
go to stdout, diagnostics and progress to stderr, and exit codes distinguish
the common failure classes.

Subcommands:
    forms         list available poetic forms
    models        list locally installed Ollama models
    generate      generate poems; append (default) or exclusively create a file
    init-config   write a sample config file (never overwrites)
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import forms as forms_mod
from .config import (
    SAMPLE_CONFIG,
    app_config_dir,
    default_config_path,
    load_config,
)
from .errors import (
    EXIT_CONFIG,
    EXIT_CONNECTION,
    EXIT_INTERRUPTED,
    EXIT_INVALID_ARGS,
    EXIT_OK,
    EXIT_PARTIAL,
    AdversarialPoetryError,
    Cancelled,
    ConnectionFailure,
    GenerationError,
)
from .generation import GenerationService, PoemRequest
from .ollama_client import OllamaClient
from .paths import resolve_output_path
from .safeio import NEW_FILE_MODE, ensure_app_dir, write_batch
from .signals import cancellation_scope


def _eprint(*a: object) -> None:
    print(*a, file=sys.stderr)


def _service(args: argparse.Namespace) -> tuple[GenerationService, object]:
    config = load_config(args.config, extra_roots=getattr(args, "output_roots", None))
    client = OllamaClient(config.ollama_endpoint, timeout=config.request_timeout)
    return GenerationService(client, config), config


# --- subcommands ------------------------------------------------------------
def cmd_forms(args: argparse.Namespace) -> int:
    for name in forms_mod.list_forms():
        print(f"{name}\t{forms_mod.FORMS[name].summary}")
    return EXIT_OK


def cmd_models(args: argparse.Namespace) -> int:
    service, _ = _service(args)
    try:
        models = service.client.list_models()
    except ConnectionFailure as exc:
        _eprint(f"error: {exc}")
        return EXIT_CONNECTION
    if not models:
        _eprint("no models installed; pull one with: ollama pull <model>")
        return EXIT_OK
    for m in models:
        print(m)
    return EXIT_OK


def cmd_generate(args: argparse.Namespace) -> int:
    service, config = _service(args)

    req = PoemRequest(
        brief=args.brief,
        form=args.form or config.default_form,
        count=args.count,
        model=args.model,
        temperature=args.temperature,
        seed=args.seed,
        title=args.title,
    )

    def progress(done: int, total: int, _poem: str) -> None:
        _eprint(f"[{done}/{total}] generated")

    with cancellation_scope() as cancel:
        try:
            poems = service.generate_batch(req, cancel=cancel, on_progress=progress)
        except Cancelled:
            _eprint("cancelled before any poem was generated")
            return EXIT_INTERRUPTED
        except ConnectionFailure as exc:
            _eprint(f"error: {exc}")
            return EXIT_CONNECTION
        except GenerationError as exc:
            _eprint(f"error: {exc}")
            return EXIT_PARTIAL
        except AdversarialPoetryError as exc:
            _eprint(f"error: {exc}")
            return getattr(exc, "exit_code", EXIT_INVALID_ARGS)

        # Output. --stdout prints poems and never touches the filesystem.
        if args.stdout:
            print(("\n\n").join(poems))
            return EXIT_INTERRUPTED if cancel.is_set() else EXIT_OK

        mode = "create" if args.create else "append"
        try:
            target = resolve_output_path(args.output, config.default_output_root)
            written = write_batch(
                poems, target, config.allowed_output_roots, mode=mode
            )
        except AdversarialPoetryError as exc:
            _eprint(f"error: {exc}")
            return getattr(exc, "exit_code", EXIT_INVALID_ARGS)
        except ValueError as exc:
            _eprint(f"error: {exc}")
            return EXIT_INVALID_ARGS

        _eprint(f"wrote {len(poems)} poem(s), {written} bytes ({mode}) -> {target}")
        print(target)
        return EXIT_INTERRUPTED if cancel.is_set() else EXIT_OK


def cmd_init_config(args: argparse.Namespace) -> int:
    dest = Path(os.path.expanduser(args.path)) if args.path else default_config_path()
    ensure_app_dir(dest.parent)
    # Exclusive create, owner-only; never overwrite an existing config.
    try:
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, NEW_FILE_MODE)
    except FileExistsError:
        _eprint(f"refusing to overwrite existing config: {dest}")
        return EXIT_INVALID_ARGS
    except OSError as exc:
        _eprint(f"error: cannot write config {dest}: {exc}")
        return EXIT_CONFIG
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(SAMPLE_CONFIG)
    _eprint(f"wrote sample config -> {dest}")
    print(dest)
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="adversarial-poetry",
        description="Deterministic local generator for adversarial-poetry artifacts.",
    )
    p.add_argument("--config", help="explicit path to a config.toml")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("forms", help="list available poetic forms")
    sp.set_defaults(func=cmd_forms)

    sp = sub.add_parser("models", help="list locally installed Ollama models")
    sp.add_argument(
        "--output-root", action="append", dest="output_roots", metavar="DIR",
        help=argparse.SUPPRESS,
    )
    sp.set_defaults(func=cmd_models)

    sp = sub.add_parser("generate", help="generate poems and save them")
    sp.add_argument("brief", help="the subject/brief the poem is about")
    sp.add_argument("-f", "--form", help="poetic form (see `forms`)")
    sp.add_argument("-n", "--count", type=int, default=1, help="number of poems")
    sp.add_argument("-m", "--model", help="Ollama writer model")
    sp.add_argument("-t", "--temperature", type=float, help="sampling temperature")
    sp.add_argument(
        "-s", "--seed", type=int,
        help="base seed; poem i uses seed+i for repeatable batches",
    )
    sp.add_argument("--title", help="optional poem title to request")
    sp.add_argument(
        "-o", "--output", help="output file path (resolved against allowed roots)",
    )
    sp.add_argument(
        "--create", action="store_true",
        help="exclusively create the file; fail if it exists (default: append)",
    )
    sp.add_argument(
        "--stdout", action="store_true",
        help="print poems to stdout instead of writing to a file",
    )
    sp.add_argument(
        "--output-root", action="append", dest="output_roots", metavar="DIR",
        help="additional allowed output root (may be repeated)",
    )
    sp.set_defaults(func=cmd_generate)

    sp = sub.add_parser("init-config", help="write a sample config file")
    sp.add_argument("--path", help="where to write (default: XDG config path)")
    sp.set_defaults(func=cmd_init_config)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # generate requires an output target unless --stdout.
    if args.command == "generate" and not args.stdout and not args.output:
        parser.error("generate requires -o/--output (or use --stdout)")

    try:
        return args.func(args)
    except AdversarialPoetryError as exc:
        _eprint(f"error: {exc}")
        return getattr(exc, "exit_code", EXIT_CONFIG)


if __name__ == "__main__":
    raise SystemExit(main())
