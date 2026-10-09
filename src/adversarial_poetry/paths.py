"""User-facing path resolution rules (the *policy*, not the *I/O*).

This module turns a user-supplied path string into an absolute ``Path`` using
rules that are documented and predictable. It deliberately does **not** open
anything, does not resolve symlinks, and does not touch the filesystem beyond
what is needed to expand a leading ``~``. The security-critical, race-aware
opening lives in :mod:`adversarial_poetry.safeio`.

Resolution rules (documented contract)
--------------------------------------
Given a raw path string ``p``:

1. A leading ``~`` or ``~user`` is expanded explicitly to the corresponding
   home directory. This is the *only* expansion performed.
2. Arbitrary environment variables are **not** expanded. ``$HOME`` and
   ``${FOO}`` are treated as literal path components. This is a deliberate
   safety choice for user-provided output paths.
3. If ``p`` is absolute after tilde expansion, it is used as-is.
4. If ``p`` is relative, it is resolved against the configured
   *default output root* (the first configured allowed output root), **not**
   against the process working directory. MCP behavior therefore never
   depends on an unexplained CWD.
5. The result is lexically normalised (``..`` and ``.`` collapsed) so that an
   obvious traversal like ``a/../../etc`` is detectable, but no symlinks are
   followed here. Symlink-escape and allowed-root enforcement happen at open
   time in :mod:`safeio`.

Supported, by design: absolute paths, relative paths, leading-tilde paths,
and directory/file names containing spaces and Unicode.
"""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath


def expand_leading_tilde(raw: str) -> str:
    """Expand only a leading ``~`` / ``~user``; leave everything else literal.

    Unlike :func:`os.path.expanduser` we refuse to let environment variables
    leak in, and we only ever touch the first path segment.
    """
    if not raw:
        return raw
    if raw[0] != "~":
        return raw
    # os.path.expanduser handles both "~" and "~user"; it only ever rewrites
    # the leading segment, which is exactly what we want. It does not expand
    # environment variables, so no $VAR leakage occurs here.
    expanded = os.path.expanduser(raw)
    # If expansion failed (unknown user, or HOME unset), expanduser returns the
    # string unchanged with the leading "~" intact. Leave it for the caller to
    # resolve/reject rather than silently inventing a home directory.
    return expanded


def resolve_output_path(raw: str, default_root: Path) -> Path:
    """Resolve a user output-path string to an absolute, lexically-clean Path.

    See the module docstring for the full contract. ``default_root`` must be an
    absolute path (a configured allowed output root); relative inputs resolve
    against it.
    """
    if not str(raw).strip():
        raise ValueError("empty output path")

    expanded = expand_leading_tilde(str(raw))
    p = Path(expanded)

    if not p.is_absolute():
        if not default_root.is_absolute():
            raise ValueError("default output root must be absolute")
        p = default_root / p

    # Lexical normalisation without touching the filesystem / following links.
    # os.path.normpath collapses "." and ".." purely textually.
    normalised = os.path.normpath(str(p))
    return Path(normalised)


def is_within(root: Path, candidate: Path) -> bool:
    """Return True if ``candidate`` is ``root`` or lexically nested under it.

    Both arguments must already be absolute and normalised. This is a *fast,
    lexical* pre-check only; it is never the sole gate -- :mod:`safeio` re-checks
    using real inodes and ``O_NOFOLLOW`` directory-relative opens.
    """
    root_parts = PurePosixPath(root).parts
    cand_parts = PurePosixPath(candidate).parts
    if len(cand_parts) < len(root_parts):
        return False
    return cand_parts[: len(root_parts)] == root_parts


def relative_components(root: Path, target: Path) -> list[str]:
    """Return the path components of ``target`` relative to ``root``.

    Rejects any ``..`` component outright (traversal). Assumes both paths are
    absolute and normalised and that ``target`` is lexically within ``root``.
    """
    rel = PurePosixPath(target).relative_to(PurePosixPath(root))
    comps = [c for c in rel.parts if c not in ("", ".")]
    if any(c == ".." for c in comps):
        raise ValueError(f"path traversal component in {target!r}")
    return comps
