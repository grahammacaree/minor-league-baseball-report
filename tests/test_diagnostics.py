from __future__ import annotations

from mlb_report import diagnostics


def test_a_level_with_no_play_by_play_is_called_out(monkeypatch):
    """The bars vanish from the email without a word, so the log says it."""
    monkeypatch.setattr(diagnostics.pitch_data, "load_cached", lambda sport, season: {})
    run = diagnostics.Run()
    diagnostics.pitch_coverage(run, (11,), 2026)

    assert run.warnings
    assert "sport 11" in run.warnings[0]
    assert "gather-pitch-data" in run.warnings[0]


def test_a_gathered_level_is_reported_without_complaint(monkeypatch):
    monkeypatch.setattr(
        diagnostics.pitch_data, "load_cached", lambda sport, season: {1: {}, 2: {}}
    )
    run = diagnostics.Run()
    diagnostics.pitch_coverage(run, (11,), 2026)

    assert run.warnings == []
    assert run.facts == [("play-by-play cached, sport 11", "2 games")]


def test_a_league_without_park_factors_is_named(monkeypatch):
    """Unadjusted numbers look exactly like adjusted ones on the page."""
    monkeypatch.setattr(
        diagnostics.park,
        "available_seasons",
        lambda league: [] if league == 2 else [2025],
    )
    run = diagnostics.Run()
    diagnostics.park_coverage(run, [1, 2], 2026)

    assert run.facts == [("park factors", "1/2 leagues")]
    assert "league(s) 2" in run.warnings[0]


def test_every_league_covered_raises_nothing(monkeypatch):
    monkeypatch.setattr(diagnostics.park, "available_seasons", lambda league: [2025])
    run = diagnostics.Run()
    diagnostics.park_coverage(run, [1, 2], 2026)

    assert run.warnings == []


def test_the_summary_carries_facts_and_warnings():
    run = diagnostics.Run()
    run.record("tracked", "30 prospects")
    run.warn("something was missing")
    rendered = diagnostics.render(run)

    assert "- tracked: 30 prospects" in rendered
    assert "### Warnings" in rendered
    assert "- something was missing" in rendered


def test_a_clean_run_has_no_warnings_heading():
    run = diagnostics.Run()
    run.record("tracked", "30 prospects")

    assert "Warnings" not in diagnostics.render(run)


def test_warnings_become_annotations_only_inside_actions(monkeypatch, capsys):
    """The annotation is what surfaces a warning on an otherwise green run."""
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    run = diagnostics.Run()
    run.warn("no play-by-play")
    diagnostics.emit(run)

    assert "::warning::no play-by-play" in capsys.readouterr().out


def test_a_local_run_is_left_unannotated(monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    run = diagnostics.Run()
    run.warn("no play-by-play")
    diagnostics.emit(run)

    printed = capsys.readouterr().out
    assert "no play-by-play" in printed
    assert "::warning::" not in printed


def test_the_run_summary_is_appended_when_one_is_offered(monkeypatch, tmp_path):
    """Appended, because other steps write to the same file."""
    summary = tmp_path / "summary.md"
    summary.write_text("earlier\n", encoding="utf-8")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    run = diagnostics.Run()
    run.record("tracked", "30 prospects")
    diagnostics.emit(run)

    written = summary.read_text(encoding="utf-8")
    assert written.startswith("earlier\n")
    assert "- tracked: 30 prospects" in written
