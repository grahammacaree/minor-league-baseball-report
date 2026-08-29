from __future__ import annotations

import json

import pytest

from mlb_report import capture_rankings, rankings


@pytest.fixture
def bundled_config(monkeypatch):
    monkeypatch.setenv("MLB_REPORT_CONFIG_HOME", "/nonexistent")


@pytest.fixture
def config_home(tmp_path, monkeypatch):
    monkeypatch.setenv("MLB_REPORT_CONFIG_HOME", str(tmp_path))
    (tmp_path / "config").mkdir()
    return tmp_path / "config"


def write(config_home, payload):
    path = config_home / rankings.RANKINGS_FILE
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_the_committed_capture_covers_every_org_in_full(bundled_config):
    """Thirty clubs, thirty deep, since a short list means a failed scrape."""
    ranked = rankings.load()
    assert len(ranked) == 900
    orgs = {entry.org_abbreviation for entry in ranked.values()}
    assert len(orgs) == 30
    assert all(entry.name and entry.position for entry in ranked.values())


def test_rankings_are_keyed_by_player_so_an_arrival_can_be_looked_up(config_home):
    write(
        config_home,
        {
            "captured": "2026-08-29",
            "orgs": [
                {
                    "name": "Chicago White Sox",
                    "abbreviation": "CWS",
                    "prospects": [
                        {
                            "rank": 4,
                            "player_id": 695722,
                            "name": "B Smith",
                            "position": "C",
                        }
                    ],
                }
            ],
        },
    )
    found = rankings.load()[695722]
    assert found.describe() == "CWS No. 4"


def test_a_player_nobody_ranked_is_simply_absent(config_home):
    write(config_home, {"captured": "2026-08-29", "orgs": []})
    assert rankings.load() == {}


def test_an_entry_without_an_id_is_skipped_rather_than_keyed_on_nothing(config_home):
    """An unassigned draftee has no id yet, and must not collapse onto a key."""
    write(
        config_home,
        {
            "captured": "2026-08-29",
            "orgs": [
                {
                    "abbreviation": "SEA",
                    "prospects": [
                        {"rank": 29, "player_id": None, "name": "Undrafted"},
                        {"rank": 30, "name": "Also Missing"},
                    ],
                }
            ],
        },
    )
    assert rankings.load() == {}


def test_a_pitcher_keeps_the_hand_the_ranking_lists_write():
    """The API calls everyone 'P'; the hand is the part worth reading."""
    lefty = {"primaryPosition": {"abbreviation": "P"}, "pitchHand": {"code": "L"}}
    righty = {"primaryPosition": {"abbreviation": "P"}, "pitchHand": {"code": "R"}}
    assert capture_rankings._position(lefty) == "LHP"
    assert capture_rankings._position(righty) == "RHP"


def test_a_position_player_is_left_as_the_api_describes_him():
    catcher = {"primaryPosition": {"abbreviation": "C"}}
    assert capture_rankings._position(catcher) == "C"


def test_a_pitcher_of_unknown_hand_stays_a_pitcher():
    vague = {"primaryPosition": {"abbreviation": "P"}, "pitchHand": {}}
    assert capture_rankings._position(vague) == "P"


def test_org_slugs_match_club_names_once_punctuation_is_dropped():
    """The club called 'D-backs' has to reach the slug 'dbacks'."""
    assert capture_rankings._normalize("D-backs") == "dbacks"
    assert capture_rankings._normalize("White Sox") == "whitesox"
    assert capture_rankings._normalize("Blue Jays") == "bluejays"


class FakePage:
    """A prospects page, reduced to what the capture actually touches."""

    def __init__(self, hrefs, expandable=False):
        self.hrefs = hrefs
        self.expanded = False
        self._expandable = expandable

    def goto(self, url, timeout=None):
        self.url = url

    def wait_for_selector(self, selector, timeout=None, state=None):
        return None

    def wait_for_function(self, expression, arg=None, timeout=None):
        return None

    def evaluate(self, expression):
        return None

    def locator(self, selector):
        return FakeLocator(0)

    def get_by_role(self, role, name=None):
        return FakeLocator(1 if self._expandable else 0, page=self)

    def eval_on_selector_all(self, selector, expression):
        return self.hrefs


class FakeLocator:
    def __init__(self, count, page=None):
        self._count = count
        self._page = page

    def count(self):
        return self._count

    def is_visible(self):
        return bool(self._count)

    @property
    def first(self):
        return self

    def click(self, timeout=None):
        if self._page is not None:
            self._page.expanded = True


def test_ranked_ids_are_read_in_page_order():
    page = FakePage(
        [
            "https://www.mlb.com/stories/kade-anderson-807739",
            "https://www.mlb.com/stories/ryan-sloan-815549",
        ]
    )
    assert capture_rankings.ranked_ids(page, "mariners") == [807739, 815549]
    assert page.url.endswith("/mariners")


def test_a_repeated_player_does_not_shift_every_rank_beneath_him():
    page = FakePage(
        [
            "https://www.mlb.com/stories/kade-anderson-807739",
            "https://www.mlb.com/stories/kade-anderson-807739",
            "https://www.mlb.com/stories/ryan-sloan-815549",
        ]
    )
    assert capture_rankings.ranked_ids(page, "mariners") == [807739, 815549]


def test_a_link_that_is_not_a_player_story_is_ignored():
    page = FakePage(
        [
            "https://www.mlb.com/stories/how-the-draft-reshaped-the-system",
            "https://www.mlb.com/stories/kade-anderson-807739",
            None,
        ]
    )
    assert capture_rankings.ranked_ids(page, "mariners") == [807739]


def test_the_full_list_is_expanded_before_reading():
    """Five prospects are served by default and the rest hide behind a click."""
    page = FakePage(
        ["https://www.mlb.com/stories/kade-anderson-807739"], expandable=True
    )
    capture_rankings.ranked_ids(page, "mariners")
    assert page.expanded
