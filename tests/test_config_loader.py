from __future__ import annotations

import json

from mlb_report import config_loader


def test_config_home_honours_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("MLB_REPORT_CONFIG_HOME", str(tmp_path))
    assert config_loader.user_config_home() == tmp_path.resolve()


def test_config_home_falls_back_to_xdg(tmp_path, monkeypatch):
    monkeypatch.delenv("MLB_REPORT_CONFIG_HOME", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert config_loader.user_config_home() == (tmp_path / "mlb-report").resolve()


def test_user_overlay_wins_over_bundled_default(tmp_path, monkeypatch):
    overlay = tmp_path / "config"
    overlay.mkdir()
    (overlay / "settings.json").write_text(json.dumps({"depth": {"watchlist": 3}}))
    monkeypatch.setenv("MLB_REPORT_CONFIG_HOME", str(tmp_path))
    assert config_loader.load_settings()["depth"]["watchlist"] == 3


def test_bundled_settings_are_valid(monkeypatch):
    monkeypatch.setenv("MLB_REPORT_CONFIG_HOME", "/nonexistent")
    settings = config_loader.load_settings()
    assert settings["org"]["team_id"] == 136
    assert settings["depth"]["watchlist"] <= settings["depth"]["notable"]
