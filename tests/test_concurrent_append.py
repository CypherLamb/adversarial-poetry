"""Concurrent-append locking across separate processes.

Each worker process appends one multi-line poem under the writer's exclusive
``flock``. With locking, no poem may be split by another process's bytes, so
every blank-line-separated block in the file must contain exactly one worker's
marker.
"""

from __future__ import annotations

import multiprocessing as mp
import os
from pathlib import Path

from adversarial_poetry.safeio import write_batch

from conftest import requires_unix

pytestmark = requires_unix

NPROC = 8
NLINES = 60


def _worker(root_str: str, target_str: str, marker: int, barrier) -> None:
    root = Path(root_str)
    target = Path(target_str)
    poem = "\n".join(f"m{marker}-line{j}" for j in range(NLINES))
    barrier.wait()  # maximise contention
    write_batch([poem], target, [root], mode="append")


def test_concurrent_appends_do_not_interleave(allowed_root: Path):
    target = allowed_root / "concurrent.txt"
    ctx = mp.get_context("fork")
    barrier = ctx.Barrier(NPROC)
    procs = [
        ctx.Process(target=_worker, args=(str(allowed_root), str(target), i, barrier))
        for i in range(NPROC)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(30)
        assert p.exitcode == 0

    text = target.read_text(encoding="utf-8")
    blocks = [b for b in text.split("\n\n") if b.strip()]
    assert len(blocks) == NPROC
    seen = set()
    for block in blocks:
        markers = {line.split("-", 1)[0] for line in block.splitlines() if line}
        # Every line in a block belongs to the same worker (no interleaving).
        assert len(markers) == 1, f"interleaved block: {markers}"
        seen.add(next(iter(markers)))
    # All workers' poems are present exactly once.
    assert seen == {f"m{i}" for i in range(NPROC)}
