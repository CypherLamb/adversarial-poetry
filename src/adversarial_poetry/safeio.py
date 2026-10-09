"""Race-aware, Unix-safe writing of poems into allowed output roots.

This is the security core. It does not trust path strings, string-prefix
checks, or model instructions. Every write is confined to a configured
*allowed output root* and is opened through directory-relative, symlink-refusing
system calls so that a symlink swapped in mid-flight cannot redirect the write
outside the root (TOCTOU hardening).

What this guarantees on Linux (and other Unixes exposing the same flags):

* **Confinement.** The target must lexically sit inside an allowed root *and*
  every real directory component from the root down to the parent is opened
  with ``O_NOFOLLOW``; a symlink anywhere on that walk makes the open fail
  rather than escape.
* **No symlinked destination.** The final component is opened ``O_NOFOLLOW``,
  so an existing output *file* that is a symlink is refused, never followed.
* **Regular files only.** After opening we ``fstat`` the descriptor and reject
  FIFOs, devices, sockets, and directories. ``O_NONBLOCK`` during the open
  prevents a FIFO from blocking us before we can reject it.
* **Never a silent overwrite.** ``create`` mode uses ``O_EXCL`` and fails if the
  destination exists. ``append`` mode only ever adds to the end; there is no
  truncating/overwriting mode at all.
* **Owner-only new files.** New files are created mode ``0o600``. Existing files
  and directories are never ``chmod``-ed.

Append locking
--------------
``append`` mode takes an exclusive ``flock`` (advisory) for the whole batch so
that poems from separate requests/processes cannot interleave, and releases it
only after the batch is fully written and ``fsync``-ed.

**Limits of advisory locking (documented honestly):** ``flock`` is *advisory*.
It serialises only against other programs that also ``flock`` the same file;
an unrelated program that writes without locking will not be held back. This is
not crash-atomic: a power loss mid-append can leave a partially written batch.
We do not claim otherwise. We do ``fsync`` after each batch to narrow the
window, but a batch is "all-or-nothing" only against cooperating writers, not
against crashes.
"""

from __future__ import annotations

import errno
import fcntl
import os
import stat
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Sequence

from .errors import PathPolicyError
from .paths import is_within, relative_components

# Permission for newly created poem files: owner read/write only.
NEW_FILE_MODE = 0o600
# Permission for application-owned directories (config/state/cache): owner only.
NEW_DIR_MODE = 0o700

# Base open flags shared by both modes. O_CLOEXEC so descriptors never leak into
# a launched MCP subprocess; O_NONBLOCK so a FIFO cannot block us before fstat.
_COMMON_FLAGS = os.O_WRONLY | os.O_NOFOLLOW | os.O_NONBLOCK
if hasattr(os, "O_CLOEXEC"):
    _COMMON_FLAGS |= os.O_CLOEXEC


def canonicalize_roots(roots: Sequence[os.PathLike | str]) -> list[Path]:
    """Resolve each configured allowed root to a real, absolute directory.

    Roots are trusted configuration, so we *do* fully resolve them (following
    any symlinks in the root path itself) once, up front. Each must already
    exist and be a directory; anything else is a configuration error surfaced
    as :class:`PathPolicyError` by the caller via validation.
    """
    out: list[Path] = []
    for r in roots:
        rp = Path(os.path.realpath(os.path.expanduser(str(r))))
        if not rp.is_absolute():
            raise PathPolicyError(f"allowed output root is not absolute: {r!r}")
        if not rp.is_dir():
            raise PathPolicyError(
                f"allowed output root does not exist or is not a directory: {rp}"
            )
        out.append(rp)
    if not out:
        raise PathPolicyError("no allowed output roots are configured")
    return out


def _select_root(target: Path, allowed_roots: Sequence[Path]) -> Path:
    for root in allowed_roots:
        if is_within(root, target):
            return root
    raise PathPolicyError(
        f"refusing to write outside the configured allowed output roots: {target}"
    )


def _open_dir_component(name: str, dir_fd: int, target: Path) -> int:
    """openat() a single intermediate directory component, refusing symlinks."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        return os.open(name, flags, dir_fd=dir_fd)
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.EMLINK):
            raise PathPolicyError(
                f"refusing to traverse a symlinked directory component "
                f"{name!r} in {target}"
            ) from exc
        if exc.errno == errno.ENOTDIR:
            raise PathPolicyError(
                f"path component {name!r} in {target} is not a directory"
            ) from exc
        if exc.errno == errno.ENOENT:
            raise PathPolicyError(
                f"parent directory does not exist for {target}"
            ) from exc
        raise PathPolicyError(f"cannot open {name!r} in {target}: {exc}") from exc


@contextmanager
def _parent_dir_fd(target: Path, allowed_roots: Sequence[Path]) -> Iterator[tuple[int, str]]:
    """Yield ``(parent_fd, filename)`` reached through non-symlink directories.

    The parent is opened by walking from a trusted (canonical) allowed root,
    refusing any symlink at each step. The yielded descriptor pins the parent
    *inode*, so a rename/symlink swap of the path after validation cannot
    redirect the subsequent openat of the final component.
    """
    root = _select_root(target, allowed_roots)
    comps = relative_components(root, target)
    if not comps:
        raise PathPolicyError(f"output target is a directory, not a file: {target}")
    *dir_comps, filename = comps

    root_flags = os.O_RDONLY | os.O_DIRECTORY
    if hasattr(os, "O_CLOEXEC"):
        root_flags |= os.O_CLOEXEC
    dir_fd = os.open(root, root_flags)
    try:
        for comp in dir_comps:
            nxt = _open_dir_component(comp, dir_fd, target)
            os.close(dir_fd)
            dir_fd = nxt
        yield dir_fd, filename
    finally:
        os.close(dir_fd)


def _open_final(parent_fd: int, filename: str, target: Path, mode: str) -> int:
    flags = _COMMON_FLAGS
    if mode == "create":
        flags |= os.O_CREAT | os.O_EXCL
    elif mode == "append":
        flags |= os.O_CREAT | os.O_APPEND
    else:  # pragma: no cover - guarded by callers
        raise ValueError(f"unknown write mode {mode!r}")

    try:
        fd = os.open(filename, flags, mode=NEW_FILE_MODE, dir_fd=parent_fd)
    except OSError as exc:
        if exc.errno == errno.EEXIST:
            raise PathPolicyError(
                f"refusing to overwrite existing file: {target}"
            ) from exc
        if exc.errno in (errno.ELOOP, errno.EMLINK):
            raise PathPolicyError(
                f"refusing to follow a symlinked destination: {target}"
            ) from exc
        if exc.errno == errno.ENXIO:
            raise PathPolicyError(
                f"refusing to write to a special file (no reader / not regular): {target}"
            ) from exc
        if exc.errno == errno.ENOENT:
            raise PathPolicyError(
                f"parent directory does not exist for {target}"
            ) from exc
        raise PathPolicyError(f"cannot open {target}: {exc}") from exc

    # Reject anything that is not a regular file (FIFO/device/socket/dir).
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode):
        os.close(fd)
        raise PathPolicyError(
            f"refusing to write to a non-regular output target: {target}"
        )

    # We only needed O_NONBLOCK to avoid blocking on a FIFO during open; on a
    # confirmed regular file it is irrelevant, but clear it for cleanliness.
    flflags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flflags & ~os.O_NONBLOCK)
    return fd


def _normalise_unix_text(text: str) -> str:
    """Preserve UTF-8 content with Unix (LF) line endings."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def write_batch(
    poems: Sequence[str],
    target: Path,
    allowed_roots: Sequence[Path],
    *,
    mode: str = "append",
    separator: str = "\n\n",
) -> int:
    """Write a batch of poems to ``target`` atomically w.r.t. cooperating writers.

    ``mode`` is ``"append"`` (default) or ``"create"`` (exclusive create).
    Returns the number of bytes written. Raises :class:`PathPolicyError` for any
    policy violation. The whole batch is written under a single exclusive
    ``flock`` in append mode so separate requests cannot interleave.
    """
    if mode not in ("append", "create"):
        raise ValueError(f"unknown write mode {mode!r}")
    if not poems:
        return 0

    # Build the payload once. Each poem keeps its own text; poems are separated
    # by ``separator``. Nothing but poem text is written (poem-only output).
    cleaned = [_normalise_unix_text(p).rstrip("\n") for p in poems]
    body = separator.join(cleaned) + "\n"

    with _parent_dir_fd(target, allowed_roots) as (parent_fd, filename):
        fd = _open_final(parent_fd, filename, target, mode)
        try:
            if mode == "append":
                # Exclusive advisory lock for the whole batch (see module docs
                # for the honest limits of flock).
                fcntl.flock(fd, fcntl.LOCK_EX)
                # If the file already had content, start the batch on a clean
                # boundary so a previous poem and this batch do not run together.
                if os.fstat(fd).st_size > 0:
                    body = separator + body
            data = body.encode("utf-8")
            _write_all(fd, data)
            os.fsync(fd)
            return len(data)
        finally:
            if mode == "append":
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                except OSError:
                    pass
            os.close(fd)


def _write_all(fd: int, data: bytes) -> None:
    """Write every byte, tolerating short writes."""
    view = memoryview(data)
    total = 0
    while total < len(view):
        total += os.write(fd, view[total:])


def ensure_app_dir(path: Path) -> Path:
    """Create an application-owned directory (config/state/cache) owner-only.

    Only directories that do not yet exist are created, with mode ``0o700``.
    Existing directories are left untouched -- we never ``chmod`` a directory
    the user already created.
    """
    if path.exists():
        if not path.is_dir():
            raise PathPolicyError(f"expected a directory at {path}")
        return path
    # Create parents too, each owner-only. We intentionally do not use a mode
    # argument on intermediate parents via makedirs (umask would interfere);
    # instead create step by step with an explicit mode.
    parts: list[Path] = []
    cur = path
    while not cur.exists():
        parts.append(cur)
        if cur.parent == cur:
            break
        cur = cur.parent
    for d in reversed(parts):
        try:
            os.mkdir(d, NEW_DIR_MODE)
        except FileExistsError:
            pass
    return path
