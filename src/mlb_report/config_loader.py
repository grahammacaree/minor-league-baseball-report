from __future__ import annotations

import json
import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def repo_root() -> Path:
    """Checkout root — shared code and committed config defaults."""
    return _REPO_ROOT


def user_config_home() -> Path:
    """
    Per-user state and secrets, never committed.

    Override with MLB_REPORT_CONFIG_HOME. Default: ~/.config/mlb-report
    (or $XDG_CONFIG_HOME/mlb-report when set).
    """
    if raw := os.environ.get("MLB_REPORT_CONFIG_HOME", "").strip():
        return Path(raw).expanduser().resolve()
    xdg = os.environ.get("XDG_CONFIG_HOME", "").strip()
    if xdg:
        return (Path(xdg).expanduser() / "mlb-report").resolve()
    return (Path.home() / ".config" / "mlb-report").resolve()


def bundled_config_dir() -> Path:
    return repo_root() / "config"


def user_config_dir() -> Path:
    return user_config_home() / "config"


def user_data_dir() -> Path:
    return user_config_home() / "data"


def _resolve_config_file(name: str) -> Path:
    """User overlay wins; otherwise the committed default."""
    user_path = user_config_dir() / name
    if user_path.exists():
        return user_path
    return bundled_config_dir() / name


def load_json(name: str) -> dict:
    path = _resolve_config_file(name)
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def load_settings() -> dict:
    return load_json("settings.json")
