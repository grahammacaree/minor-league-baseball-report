from __future__ import annotations

from datetime import date

import pytest

from mlb_report import __main__ as cli
from mlb_report import config_loader, emailer
from mlb_report.digest import Digest

REPORT_DATE = date(2026, 8, 28)


def digest(**kwargs):
    return Digest(report_date=REPORT_DATE, **kwargs)


def test_headings_and_bullets_render():
    html = emailer.markdown_to_html("## Watchlist\n\n- **A Player** — 2-4, HR\n")
    assert "<h2" in html
    assert "<li" in html
    assert "<strong>A Player</strong>" in html


def test_indented_lines_stay_inside_their_bullet():
    """A watchlist entry is one item with its season stacked underneath."""
    html = emailer.markdown_to_html(
        "- **A Player** — 2-4\n  Season at AA: 120 wRC+\n  Contact 60th\n"
    )
    assert html.count("<li") == 1
    assert html.count("<br>") == 2
    assert "120 wRC+" in html


def test_a_new_bullet_starts_a_new_item():
    html = emailer.markdown_to_html("- One\n  detail\n- Two\n")
    assert html.count("<li") == 2


def test_html_is_escaped_before_formatting():
    html = emailer.markdown_to_html("- 5 > 3 & <script>alert(1)</script>\n")
    assert "&lt;script&gt;" in html
    assert "<script>" not in html


def test_emphasis_renders_for_empty_sections():
    html = emailer.markdown_to_html("_No roster moves._")
    assert "<em" in html


def test_subject_leads_with_roster_moves():
    subject = emailer.subject_for(digest(moves=["**Optioned** — sent to Everett."]))
    assert "1 roster move" in subject


def test_subject_falls_back_to_performances_then_trends():
    assert "2 notable" in emailer.subject_for(digest(notable=["a", "b"]))
    assert "trends only" in emailer.subject_for(digest(trends=["a"]))
    assert "quiet night" in emailer.subject_for(digest())


def test_subject_carries_the_date():
    assert "28 Aug" in emailer.subject_for(digest())


def test_recipients_are_read_from_the_config_home(tmp_path, monkeypatch):
    monkeypatch.setenv("MLB_REPORT_CONFIG_HOME", str(tmp_path))
    (tmp_path / "user.json").write_text('{"recipients": [{"email": "g@example.com"}]}')
    assert config_loader.recipients() == ["g@example.com"]


def test_a_recipient_named_but_not_addressed_is_an_error(tmp_path, monkeypatch):
    """Somebody was meant to be on this list, and silently is not."""
    monkeypatch.setenv("MLB_REPORT_CONFIG_HOME", str(tmp_path))
    (tmp_path / "user.json").write_text(
        '{"recipients": [{"name": "G", "email": "g@example.com"},'
        ' {"name": "No address"}]}'
    )
    with pytest.raises(ValueError, match="Unusable recipient"):
        config_loader.recipients()


def test_a_missing_user_file_explains_itself(tmp_path, monkeypatch):
    monkeypatch.setenv("MLB_REPORT_CONFIG_HOME", str(tmp_path))
    with pytest.raises(FileNotFoundError, match="user.example.json"):
        config_loader.load_user()


def test_env_file_is_parsed_and_comments_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv("MLB_REPORT_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("SMTP_HOST", raising=False)
    (tmp_path / ".env").write_text(
        "# comment\n\nSMTP_HOST=smtp.example.com\nBAD LINE\n"
    )
    assert config_loader.load_env()["SMTP_HOST"] == "smtp.example.com"


def test_process_environment_overrides_the_env_file(tmp_path, monkeypatch):
    """CI supplies secrets as environment variables, not as a file."""
    monkeypatch.setenv("MLB_REPORT_CONFIG_HOME", str(tmp_path))
    (tmp_path / ".env").write_text("SMTP_HOST=from-file\n")
    monkeypatch.setenv("SMTP_HOST", "from-ci")
    assert config_loader.load_env()["SMTP_HOST"] == "from-ci"


@pytest.fixture
def delivery(monkeypatch):
    """A stand-in for the outside world, recording whether anything was sent."""
    sent: list[dict] = []
    monkeypatch.setattr(emailer, "send", lambda **kwargs: sent.append(kwargs))
    monkeypatch.setattr(cli.emailer, "send", lambda **kwargs: sent.append(kwargs))
    monkeypatch.setattr(cli.config_loader, "recipients", lambda: ["hi@example.com"])
    monkeypatch.setattr(
        cli.config_loader,
        "load_env",
        lambda: {
            "SMTP_HOST": "smtp.example.com",
            "SMTP_USER": "user",
            "SMTP_PASSWORD": "secret",
            "MAIL_FROM": "digest@example.com",
        },
    )
    return sent


def deliver_with(monkeypatch, user: dict, **digest_kwargs) -> None:
    monkeypatch.setattr(cli.config_loader, "load_user", lambda: user)
    cli._deliver(digest(**digest_kwargs), "the digest")


def test_a_quiet_night_sends_nothing_unless_asked(monkeypatch, delivery):
    """The season ends in September; the default cannot be a daily empty email."""
    deliver_with(monkeypatch, {})
    assert delivery == []


def test_a_quiet_night_is_sent_when_that_is_the_preference(monkeypatch, delivery):
    deliver_with(monkeypatch, {"send_when_quiet": True})
    assert len(delivery) == 1


def test_a_night_with_news_is_always_sent(monkeypatch, delivery):
    deliver_with(monkeypatch, {}, moves=["**Optioned** — sent to Everett."])
    assert len(delivery) == 1


def test_a_malformed_sender_stops_the_send(monkeypatch, delivery):
    """The sender lands in a header too."""
    monkeypatch.setattr(
        cli.config_loader,
        "load_env",
        lambda: {
            "SMTP_HOST": "smtp.example.com",
            "SMTP_USER": "user",
            "SMTP_PASSWORD": "secret",
            "MAIL_FROM": "digest@example.com\nBcc: everyone@example.com",
        },
    )
    monkeypatch.setattr(cli.config_loader, "load_user", lambda: {})
    assert cli._deliver(digest(moves=["a move"]), "the digest") == 1
    assert delivery == []
