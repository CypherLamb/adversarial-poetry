"""Filesystem-security tests for the Unix-safe writer."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from adversarial_poetry.errors import PathPolicyError
from adversarial_poetry.safeio import canonicalize_roots, write_batch

from conftest import requires_unix

pytestmark = requires_unix


def test_create_new_file_owner_only(allowed_root: Path):
    target = allowed_root / "poem.txt"
    n = write_batch(["alpha\nbeta"], target, [allowed_root], mode="create")
    assert target.is_file()
    assert n > 0
    mode = stat.S_IMODE(os.lstat(target).st_mode)
    assert mode == 0o600
    assert target.read_text(encoding="utf-8") == "alpha\nbeta\n"


def test_create_refuses_overwrite(allowed_root: Path):
    target = allowed_root / "poem.txt"
    write_batch(["first"], target, [allowed_root], mode="create")
    with pytest.raises(PathPolicyError):
        write_batch(["second"], target, [allowed_root], mode="create")
    assert target.read_text(encoding="utf-8") == "first\n"


def test_append_adds_separated_batches(allowed_root: Path):
    target = allowed_root / "book.txt"
    write_batch(["one"], target, [allowed_root], mode="append")
    write_batch(["two"], target, [allowed_root], mode="append")
    text = target.read_text(encoding="utf-8")
    assert "one" in text and "two" in text
    # Second batch is separated from the first by a blank line.
    assert "one\n\ntwo" in text


def test_batch_of_multiple_poems_separated(allowed_root: Path):
    target = allowed_root / "multi.txt"
    write_batch(["a", "b", "c"], target, [allowed_root], mode="create")
    assert target.read_text(encoding="utf-8") == "a\n\nb\n\nc\n"


def test_unix_line_endings_preserved(allowed_root: Path):
    target = allowed_root / "crlf.txt"
    write_batch(["x\r\ny\rz"], target, [allowed_root], mode="create")
    assert target.read_text(encoding="utf-8") == "x\ny\nz\n"


def test_reject_write_outside_roots(allowed_root: Path, tmp_path: Path):
    outside = tmp_path / "elsewhere.txt"
    with pytest.raises(PathPolicyError):
        write_batch(["nope"], outside, [allowed_root], mode="create")


def test_reject_missing_parent(allowed_root: Path):
    target = allowed_root / "no_such_dir" / "poem.txt"
    with pytest.raises(PathPolicyError):
        write_batch(["x"], target, [allowed_root], mode="create")


def test_reject_symlinked_destination(allowed_root: Path, tmp_path: Path):
    # A symlink *file* inside the root pointing anywhere must not be followed.
    victim = tmp_path / "victim.txt"
    link = allowed_root / "poem.txt"
    os.symlink(victim, link)
    with pytest.raises(PathPolicyError):
        write_batch(["x"], link, [allowed_root], mode="append")
    assert not victim.exists()


def test_reject_symlinked_parent_component(allowed_root: Path, tmp_path: Path):
    # A symlinked directory *component* on the path must be refused.
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    link_dir = allowed_root / "sneaky"
    os.symlink(outside_dir, link_dir)
    target = allowed_root / "sneaky" / "poem.txt"
    with pytest.raises(PathPolicyError):
        write_batch(["x"], target, [allowed_root], mode="create")
    assert not (outside_dir / "poem.txt").exists()


def test_reject_fifo_target(allowed_root: Path):
    fifo = allowed_root / "pipe"
    os.mkfifo(fifo)
    with pytest.raises(PathPolicyError):
        write_batch(["x"], fifo, [allowed_root], mode="append")


def test_reject_directory_target(allowed_root: Path):
    d = allowed_root / "adir"
    d.mkdir()
    with pytest.raises(PathPolicyError):
        write_batch(["x"], d, [allowed_root], mode="append")


def test_canonicalize_roots_requires_existing_dir(tmp_path: Path):
    with pytest.raises(PathPolicyError):
        canonicalize_roots([tmp_path / "does-not-exist"])
    file = tmp_path / "f.txt"
    file.write_text("x")
    with pytest.raises(PathPolicyError):
        canonicalize_roots([file])


def test_canonicalize_roots_empty_rejected():
    with pytest.raises(PathPolicyError):
        canonicalize_roots([])
