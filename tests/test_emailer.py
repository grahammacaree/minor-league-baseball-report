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


def test_subject_reports_a_move():
    subject = emailer.subject_for(digest(moves=["**Optioned** — sent to Everett."]))
    assert subject == "Mariners farm 28 Aug: 1 move"


def test_a_player_arriving_or_leaving_outranks_an_ordinary_move():
    """Who the organization has is the thing worth knowing before opening."""
    subject = emailer.subject_for(
        digest(arrivals=["**C Boston Smith**"], moves=["**Optioned**"])
    )
    assert subject == "Mariners farm 28 Aug: 1 roster change"


def test_several_of_something_is_pluralised():
    subject = emailer.subject_for(digest(moves=["one", "two", "three"]))
    assert subject == "Mariners farm 28 Aug: 3 moves"


def test_good_performances_are_not_news():
    """Counting them trained the reader to ignore a number he could not act on."""
    assert emailer.subject_for(digest(standouts=2)) == "Mariners farm 28 Aug"


def test_a_night_with_no_news_is_just_the_date():
    assert emailer.subject_for(digest()) == "Mariners farm 28 Aug"


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


def test_a_skills_line_becomes_bars():
    """Percentiles are easier to scan as lengths than as a row of numbers."""
    html = emailer.markdown_to_html(
        "- **A Player** — 2-4\n"
        "  Contact% 78.2% 58th · HR/FB 12.4% 77th · BB% 9.1% 17th\n"
    )
    assert "<table" in html
    assert "Contact%" in html and "58th" in html
    # The rate itself rides along, so the rank is never the only number.
    assert "78.2%" in html and "12.4%" in html
    # Widths track the percentiles, so a stronger skill draws a longer bar.
    assert 'width="63"' in html and 'width="83"' in html


def test_an_inverted_metric_keeps_its_arrow():
    """The arrow is what tells the reader which end of the rate is the good one."""
    html = emailer.markdown_to_html(
        "- **A Pitcher** — 6 IP\n  SwStr% 13.1% 66th · BB%\u2193 5.1% 98th\n"
    )
    assert "BB%\u2193" in html
    assert "5.1%" in html


def test_a_bar_is_never_completely_empty():
    """A first-percentile skill still needs something to see."""
    html = emailer.markdown_to_html(
        "- **A Player** — 2-4\n  Contact% 61.0% 1st · HR/FB 20.0% 94th\n"
    )
    assert 'width="1"' in html


def test_lines_that_are_not_skills_are_left_as_text():
    """A line without the name-rate-rank shape stays prose."""
    line = "Season at AA (TEX): 3.32 FIP, 73 FIP- in 352 BF"
    assert emailer.skill_bars(line) is None
    html = emailer.markdown_to_html(f"- **A Player** — 2-4\n  {line}\n")
    assert "3.32 FIP" in html
    assert "<table" not in html


def test_text_after_bars_is_not_pushed_away_by_a_break():
    """The table has already ended the line; a break would open a gap."""
    html = emailer.markdown_to_html(
        "- **A Player** — 2-4\n"
        "  Contact% 78.2% 58th · HR/FB 12.4% 77th\n"
        "  Before that at AA: 123 wRC+ in 297 PA\n"
    )
    assert "</table><br>" not in html


def test_level_headings_render_as_headings():
    """Longer prefixes are checked first, or "### AAA" arrives as body text."""
    html = emailer.markdown_to_html("## Played yesterday\n\n### AAA\n\n- **A** — 2-4\n")
    assert "<h3" in html
    assert "AAA</h3>" in html
    assert "### AAA" not in html
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


def test_a_linked_name_becomes_an_anchor():
    html = emailer.markdown_to_html(
        "- **1. LHP [Kade Anderson](https://www.mlb.com/player/807739)**: 6 IP"
    )
    assert '<a href="https://www.mlb.com/player/807739"' in html
    assert ">Kade Anderson</a>" in html
    assert "](" not in html


def test_bracketed_text_that_is_not_a_link_is_left_alone():
    assert "[not a link]" in emailer.markdown_to_html("- [not a link] and more")
