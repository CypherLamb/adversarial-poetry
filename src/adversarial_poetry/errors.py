"""Exit codes and the exception hierarchy shared across entry points.

Exit codes are stable and script-friendly. They are deliberately distinct so
that a wrapping shell script can tell apart the common failure classes.
"""

from __future__ import annotations

# --- Exit codes -------------------------------------------------------------
# 0  success
# 2  invalid arguments (argparse also uses 2 for parse errors)
# 3  configuration failure
# 4  connection failure (e.g. Ollama endpoint unreachable)
# 5  partial generation failure (some, not all, poems produced/written)
# 130 interrupted (SIGINT), by Unix convention 128 + signal number
# 143 terminated (SIGTERM)
EXIT_OK = 0
EXIT_INVALID_ARGS = 2
EXIT_CONFIG = 3
EXIT_CONNECTION = 4
EXIT_PARTIAL = 5
EXIT_INTERRUPTED = 130
EXIT_TERMINATED = 143


class AdversarialPoetryError(Exception):
    """Base class for all errors raised by this package."""

    exit_code: int = 1


class ConfigError(AdversarialPoetryError):
    """Configuration could not be loaded or is invalid."""

    exit_code = EXIT_CONFIG


class PathPolicyError(AdversarialPoetryError):
    """A requested output path violates the filesystem-safety policy.

    This covers path traversal, symlink escapes, writing outside allowed
    roots, non-regular output targets, and refusing to overwrite.
    """

    exit_code = EXIT_INVALID_ARGS


class ConnectionFailure(AdversarialPoetryError):
    """The configured Ollama endpoint could not be reached or errored."""

    exit_code = EXIT_CONNECTION


class GenerationError(AdversarialPoetryError):
    """Generation failed for one or more requested poems."""

    exit_code = EXIT_PARTIAL


class Cancelled(AdversarialPoetryError):
    """Raised internally to unwind cleanly on SIGINT/SIGTERM/EOF."""

    exit_code = EXIT_INTERRUPTED
