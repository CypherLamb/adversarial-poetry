"""Path-resolution policy tests (spaces, Unicode, tilde, relative, traversal)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from adversarial_poetry.paths import (
    expand_leading_tilde,
    is_within,
    relative_components,
    resolve_output_path,
)


def test_absolute_path_unchanged(tmp_path: Path):
    root = tmp_path
    target = tmp_path / "subdir" / "poem.txt"
    assert resolve_output_path(str(target), root) == target


def test_relative_resolves_against_default_root_not_cwd(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    got = resolve_output_path("drafts/poem.txt", root)
    assert got == root / "drafts" / "poem.txt"


def test_spaces_and_unicode(tmp_path: Path):
    root = tmp_path / "root"
    got = resolve_output_path("Ã©motions et nuÃ¢ges/poÃ¨me final.txt", root)
    assert got == root / "Ã©motions et nuÃ¢ges" / "poÃ¨me final.txt"


def test_leading_tilde_expands(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    expanded = expand_leading_tilde("~/poems/x.txt")
    assert expanded == str(tmp_path / "poems" / "x.txt")


def test_env_vars_not_expanded(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SECRET", "/etc")
    # $SECRET must be treated as a literal component, never expanded.
    got = resolve_output_path("$SECRET/poem.txt", tmp_path)
    assert "etc" not in got.parts
    assert "$SECRET" in got.parts


def test_lexical_traversal_visible(tmp_path: Path):
    root = tmp_path / "a" / "b"
    got = resolve_output_path("../../escape.txt", root)
    # normpath collapses; result should sit above the root, so is_within fails.
    assert not is_within(tmp_path / "a" / "b", got)


def test_is_within():
    assert is_within(Path("/srv/out"), Path("/srv/out/x/y.txt"))
    assert is_within(Path("/srv/out"), Path("/srv/out"))
    assert not is_within(Path("/srv/out"), Path("/srv/output/y.txt"))
    assert not is_within(Path("/srv/out"), Path("/srv"))


def test_relative_components_rejects_dotdot():
    with pytest.raises(ValueError):
        relative_components(Path("/root"), Path("/root/../etc/passwd"))


def test_empty_path_rejected(tmp_path: Path):
    with pytest.raises(ValueError):
        resolve_output_path("   ", tmp_path)
