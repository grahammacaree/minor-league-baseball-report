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


def test_subject_falls_back_to_standouts_then_calls_it_quiet():
    """The watchlist playing is not news, so it does not reach the subject."""
    assert "2 notable" in emailer.subject_for(digest(standouts=2))
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


def test_a_skills_line_becomes_bars():
    """Percentiles are easier to scan as lengths than as a row of numbers."""
    html = emailer.markdown_to_html(
        "- **A Player** — 2-4\n  Contact 58th · Power 77th · Discipline 17th\n"
    )
    assert "<table" in html
    assert "Contact" in html and "58th" in html
    # Widths track the percentiles, so a stronger skill draws a longer bar.
    assert 'width="63"' in html and 'width="83"' in html


def test_a_bar_is_never_completely_empty():
    """A first-percentile skill still needs something to see."""
    html = emailer.markdown_to_html(
        "- **A Player** — 2-4\n  Contact 1st · Power 94th\n"
    )
    assert 'width="1"' in html


def test_lines_that_are_not_skills_are_left_as_text():
    """The batted-ball line leads with a rate, so it stays prose."""
    line = "34% grounders (10th) · 50% pulled (92nd)"
    assert emailer.skill_bars(line) is None
    html = emailer.markdown_to_html(f"- **A Player** — 2-4\n  {line}\n")
    assert "34% grounders" in html
    assert "<table" not in html


def test_text_after_bars_is_not_pushed_away_by_a_break():
    """The table has already ended the line; a break would open a gap."""
    html = emailer.markdown_to_html(
        "- **A Player** — 2-4\n  Contact 58th · Power 77th\n  34% grounders (10th)\n"
    )
    assert "</table><br>" not in html


def test_level_headings_render_as_headings():
    """Longer prefixes are checked first, or "### AAA" arrives as body text."""
    html = emailer.markdown_to_html("## Played yesterday\n\n### AAA\n\n- **A** — 2-4\n")
    assert "<h3" in html
    assert "AAA</h3>" in html
    assert "### AAA" not in html
