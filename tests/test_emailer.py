from __future__ import annotations

from datetime import date

import pytest

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
    (tmp_path / "user.json").write_text(
        '{"recipients": [{"name": "G", "email": "g@example.com"},'
        ' {"name": "No address"}]}'
    )
    assert config_loader.recipients() == ["g@example.com"]


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
