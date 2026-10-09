"""Configuration and XDG base-directory handling.

Configuration is TOML, located (in order of precedence):

1. an explicit ``--config PATH`` supplied by the user, otherwise
2. ``$XDG_CONFIG_HOME/adversarial-poetry/config.toml``
   (``~/.config/adversarial-poetry/config.toml`` when ``XDG_CONFIG_HOME``
   is unset).

Optional application state and cache live under ``$XDG_STATE_HOME`` and
``$XDG_CACHE_HOME`` (with the usual ``~/.local/state`` and ``~/.cache``
fallbacks). Application-owned directories we create are owner-only (0700).

The configured endpoint stays local by default; we never change network
bindings, firewall rules, or the Ollama service. There is no cloud fallback.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - project requires >=3.11
    raise RuntimeError("adversarial-poetry requires Python 3.11+")

from .errors import ConfigError
from .safeio import canonicalize_roots

APP_NAME = "adversarial-poetry"
DEFAULT_ENDPOINT = "http://127.0.0.1:11434"


# --- XDG helpers ------------------------------------------------------------
def _xdg_dir(env_var: str, fallback: Path) -> Path:
    raw = os.environ.get(env_var)
    if raw and os.path.isabs(raw):
        return Path(raw)
    return fallback


def config_home() -> Path:
    return _xdg_dir("XDG_CONFIG_HOME", Path.home() / ".config")


def state_home() -> Path:
    return _xdg_dir("XDG_STATE_HOME", Path.home() / ".local" / "state")


def cache_home() -> Path:
    return _xdg_dir("XDG_CACHE_HOME", Path.home() / ".cache")


def app_config_dir() -> Path:
    return config_home() / APP_NAME


def app_state_dir() -> Path:
    return state_home() / APP_NAME


def app_cache_dir() -> Path:
    return cache_home() / APP_NAME


def default_config_path() -> Path:
    return app_config_dir() / "config.toml"


@dataclass(frozen=True)
class Config:
    """Resolved runtime configuration."""

    ollama_endpoint: str = DEFAULT_ENDPOINT
    # Local Ollama writer models. Empty by default: we never assume any model
    # is installed. The user must list the models they have pulled.
    writer_models: tuple[str, ...] = ()
    default_model: str | None = None
    default_form: str = "free_verse"
    temperature: float = 0.8
    seed: int | None = None
    request_timeout: float = 120.0
    # Canonicalised allowed output roots. Writing is refused unless non-empty.
    allowed_output_roots: tuple[Path, ...] = ()
    # Source path this config was loaded from (for diagnostics), if any.
    source_path: Path | None = None

    @property
    def default_output_root(self) -> Path:
        if not self.allowed_output_roots:
            raise ConfigError(
                "no allowed_output_roots configured; set at least one to "
                "enable writing poems"
            )
        return self.allowed_output_roots[0]

    def resolved_model(self, override: str | None = None) -> str:
        model = override or self.default_model
        if not model:
            raise ConfigError(
                "no model specified and no default_model configured; pass a "
                "model explicitly or set default_model / writer_models in config"
            )
        return model


def _coerce_roots(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    raise ConfigError(f"allowed_output_roots must be a string or list, got {type(value)}")


def load_config(
    explicit_path: str | os.PathLike | None = None,
    *,
    extra_roots: list[str] | None = None,
) -> Config:
    """Load configuration from TOML, applying XDG fallbacks.

    ``extra_roots`` (e.g. from a ``--output-root`` CLI flag) are appended to the
    configured allowed roots. A missing config file is not an error unless an
    explicit ``--config`` path was given that does not exist.
    """
    path: Path | None
    if explicit_path is not None:
        path = Path(os.path.expanduser(str(explicit_path)))
        if not path.is_file():
            raise ConfigError(f"config file not found: {path}")
    else:
        candidate = default_config_path()
        path = candidate if candidate.is_file() else None

    data: dict[str, Any] = {}
    if path is not None:
        try:
            with open(path, "rb") as fh:
                data = tomllib.load(fh)
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"invalid TOML in {path}: {exc}") from exc
        except OSError as exc:
            raise ConfigError(f"cannot read config {path}: {exc}") from exc

    gen = data.get("generation", {}) if isinstance(data.get("generation"), dict) else {}
    out = data.get("output", {}) if isinstance(data.get("output"), dict) else {}
    oll = data.get("ollama", {}) if isinstance(data.get("ollama"), dict) else {}

    root_strings = _coerce_roots(out.get("allowed_roots"))
    if extra_roots:
        root_strings.extend(extra_roots)

    roots: tuple[Path, ...] = ()
    if root_strings:
        roots = tuple(canonicalize_roots(root_strings))

    writer_models = tuple(str(m) for m in (gen.get("writer_models") or []))
    default_model = gen.get("default_model")
    if default_model is None and writer_models:
        default_model = writer_models[0]

    try:
        cfg = Config(
            ollama_endpoint=str(oll.get("endpoint", DEFAULT_ENDPOINT)),
            writer_models=writer_models,
            default_model=default_model,
            default_form=str(gen.get("default_form", "free_verse")),
            temperature=float(gen.get("temperature", 0.8)),
            seed=gen.get("seed"),
            request_timeout=float(oll.get("request_timeout", 120.0)),
            allowed_output_roots=roots,
            source_path=path,
        )
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"invalid configuration value: {exc}") from exc
    return cfg


def with_overrides(cfg: Config, **overrides: Any) -> Config:
    """Return a copy of ``cfg`` with non-None overrides applied."""
    clean = {k: v for k, v in overrides.items() if v is not None}
    return replace(cfg, **clean) if clean else cfg


SAMPLE_CONFIG = """\
# adversarial-poetry configuration (TOML)
#
# Copy this to $XDG_CONFIG_HOME/adversarial-poetry/config.toml
# (default: ~/.config/adversarial-poetry/config.toml) and edit.

[ollama]
# Local Ollama endpoint. Kept local by default; this tool never changes
# network bindings or service settings.
endpoint = "http://127.0.0.1:11434"
request_timeout = 120.0

[generation]
# Models you have already pulled with `ollama pull <model>`.
# Nothing is assumed to be installed; list only what you actually have.
writer_models = []
# default_model = "llama3.1"
default_form = "free_verse"
temperature = 0.8
# seed = 1234          # set for repeatable batch generation

[output]
# Allowed output roots. Poems may only be written inside these directories.
# Use a normal home-directory path. Create it yourself beforehand.
allowed_roots = ["~/Poetry/arena-drafts"]
"""
