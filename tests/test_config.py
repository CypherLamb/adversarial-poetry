"""Config loading and XDG base-directory resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from adversarial_poetry import config as cfgmod
from adversarial_poetry.errors import ConfigError


def test_xdg_config_home_override(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xcfg"))
    assert cfgmod.config_home() == tmp_path / "xcfg"
    assert cfgmod.app_config_dir() == tmp_path / "xcfg" / "adversarial-poetry"


def test_xdg_fallbacks(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert cfgmod.config_home() == tmp_path / ".config"
    assert cfgmod.state_home() == tmp_path / ".local" / "state"
    assert cfgmod.cache_home() == tmp_path / ".cache"


def test_relative_xdg_var_ignored(monkeypatch, tmp_path: Path):
    # XDG spec: a relative XDG_* value must be ignored in favour of the default.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", "relative/path")
    assert cfgmod.config_home() == tmp_path / ".config"


def test_load_config_from_toml(tmp_path: Path):
    root = tmp_path / "out"
    root.mkdir()
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        "[ollama]\n"
        'endpoint = "http://127.0.0.1:9999"\n'
        "[generation]\n"
        'writer_models = ["m1", "m2"]\n'
        "temperature = 0.3\n"
        "[output]\n"
        f'allowed_roots = ["{root}"]\n',
        encoding="utf-8",
    )
    cfg = cfgmod.load_config(cfg_file)
    assert cfg.ollama_endpoint == "http://127.0.0.1:9999"
    assert cfg.writer_models == ("m1", "m2")
    assert cfg.default_model == "m1"  # first writer model becomes the default
    assert cfg.temperature == 0.3
    assert cfg.allowed_output_roots == (Path(root).resolve(),)
    assert cfg.default_output_root == Path(root).resolve()


def test_missing_explicit_config_errors(tmp_path: Path):
    with pytest.raises(ConfigError):
        cfgmod.load_config(tmp_path / "nope.toml")


def test_no_roots_default_output_root_errors(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "empty"))
    cfg = cfgmod.load_config(None)  # no file -> defaults, no roots
    with pytest.raises(ConfigError):
        _ = cfg.default_output_root


def test_extra_roots_appended(tmp_path: Path):
    r1 = tmp_path / "a"
    r2 = tmp_path / "b"
    r1.mkdir()
    r2.mkdir()
    cfg = cfgmod.load_config(None, extra_roots=[str(r1), str(r2)])
    assert set(cfg.allowed_output_roots) == {r1.resolve(), r2.resolve()}
