from __future__ import annotations

import json

import pytest

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


def write_user(tmp_path, monkeypatch, **user):
    monkeypatch.setenv("MLB_REPORT_CONFIG_HOME", str(tmp_path))
    (tmp_path / "user.json").write_text(json.dumps(user))


def test_recipients_are_read_in_order(tmp_path, monkeypatch):
    write_user(
        tmp_path,
        monkeypatch,
        recipients=[
            {"name": "Graham", "email": "hi@example.com"},
            {"email": "second@example.co.uk"},
        ],
    )
    assert config_loader.recipients() == ["hi@example.com", "second@example.co.uk"]


def test_surrounding_whitespace_is_trimmed(tmp_path, monkeypatch):
    write_user(tmp_path, monkeypatch, recipients=[{"email": "  hi@example.com  "}])
    assert config_loader.recipients() == ["hi@example.com"]


@pytest.mark.parametrize(
    "address",
    [
        "not-an-address",
        "no@domain",
        "@example.com",
        "hi@@example.com",
        "hi @example.com",
        "hi@example.com, sneaky@example.com",
        "",
        None,
        42,
    ],
)
def test_a_malformed_address_stops_the_send(tmp_path, monkeypatch, address):
    write_user(tmp_path, monkeypatch, recipients=[{"email": address}])
    with pytest.raises(ValueError, match="Unusable recipient"):
        config_loader.recipients()


def test_a_newline_cannot_smuggle_a_header(tmp_path, monkeypatch):
    """An address carrying a newline would append headers to the message."""
    write_user(
        tmp_path,
        monkeypatch,
        recipients=[{"email": "hi@example.com\nBcc: everyone@example.com"}],
    )
    with pytest.raises(ValueError, match="Unusable recipient"):
        config_loader.recipients()


def test_one_bad_address_is_not_quietly_dropped(tmp_path, monkeypatch):
    """Skipping it would remove someone from the list until they complained."""
    write_user(
        tmp_path,
        monkeypatch,
        recipients=[{"email": "good@example.com"}, {"email": "bad"}],
    )
    with pytest.raises(ValueError, match="position") as raised:
        config_loader.recipients()

    # Located, not quoted: in CI the entry is part of a secret and this message
    # goes to a public log.
    assert "position(s) 2" in str(raised.value)
    assert "bad" not in str(raised.value)


def test_recipients_must_be_a_list(tmp_path, monkeypatch):
    write_user(tmp_path, monkeypatch, recipients={"email": "hi@example.com"})
    with pytest.raises(ValueError, match="must be a list"):
        config_loader.recipients()


def test_no_recipients_is_empty_rather_than_an_error(tmp_path, monkeypatch):
    """Nothing is malformed; there is simply nobody to write to."""
    write_user(tmp_path, monkeypatch, recipients=[])
    assert config_loader.recipients() == []


def test_the_example_config_stays_quiet_out_of_season(monkeypatch):
    monkeypatch.setenv("MLB_REPORT_CONFIG_HOME", "/nonexistent")
    example = json.loads(
        (config_loader.repo_root() / "config/user.example.json").read_text()
    )
    assert example["send_when_quiet"] is False
    assert all(config_loader.valid_address(r["email"]) for r in example["recipients"])
