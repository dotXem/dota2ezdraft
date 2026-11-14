"""OpenDota rate limiter and the Stratz/OpenDota match merge used by Scouting (offline)."""

import pytest
import requests

import opendota_api
import scouting_api
from opendota_api import OpenDotaDailyLimitError, _RateLimiter
from scouting_api import compute_player_hero_stats, find_team_games, merge_opendota_matches

A, B = 111, 222


def _stratz_match(mid, players, radiant_win=True):
    return {
        "id": mid, "startDateTime": 1_700_000_000, "didRadiantWin": radiant_win,
        "lobbyType": 7, "leagueId": None, "radiantTeam": None, "direTeam": None,
        "pickBans": [], "players": players,
    }


def _od_row(mid, hero_id, slot=0, radiant_win=True):
    return {"match_id": mid, "player_slot": slot, "radiant_win": radiant_win,
            "start_time": 1_700_000_000, "hero_id": hero_id, "lobby_type": 7}


def test_merge_dedups_and_adds_opendota_only_matches():
    all_matches = {A: [_stratz_match(1, [{"steamAccountId": A, "heroId": 5, "isRadiant": True, "position": None}])], B: []}
    added = merge_opendota_matches(all_matches, {A: [_od_row(1, 5), _od_row(2, 8)], B: []})

    assert added == {A: 1, B: 0}
    assert [m["id"] for m in all_matches[A]] == [1, 2]
    assert len(all_matches[A][0]["players"]) == 1  # no duplicate player in the Stratz match
    stats = compute_player_hero_stats(all_matches[A], A)
    assert stats["Games"].sum() == 2


def test_merge_fills_anonymous_stratz_player():
    match = _stratz_match(1, [
        {"steamAccountId": None, "heroId": 5, "isRadiant": True, "position": "POSITION_1"},
        {"steamAccountId": 999, "heroId": 6, "isRadiant": False, "position": "POSITION_2"},
    ])
    all_matches = {A: [], B: [match]}
    merge_opendota_matches(all_matches, {A: [_od_row(1, 5)], B: []})

    assert match["players"][0]["steamAccountId"] == A
    assert all_matches[A] == [match]
    assert compute_player_hero_stats(all_matches[A], A)["Hero"].tolist() != []


def test_opendota_only_match_shared_by_two_players_is_a_team_game():
    all_matches = {A: [], B: []}
    merge_opendota_matches(all_matches, {
        A: [_od_row(3, 5, slot=0)],
        B: [_od_row(3, 8, slot=1)],
    })

    assert all_matches[A][0] is all_matches[B][0]
    assert len(all_matches[A][0]["players"]) == 2
    games = find_team_games(all_matches, [A, B], {A: "a", B: "b"})
    assert len(games) == 1 and games.iloc[0]["# Players"] == 2


def test_rate_limiter_daily_limit():
    limiter = _RateLimiter(per_minute=100, per_day=2)
    limiter.acquire()
    limiter.acquire()
    with pytest.raises(OpenDotaDailyLimitError):
        limiter.acquire()


def test_rate_limiter_waits_for_minute_window(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(opendota_api.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(opendota_api.time, "sleep", lambda s: clock.__setitem__(0, clock[0] + s))
    limiter = _RateLimiter(per_minute=2, per_day=100)
    limiter.acquire()
    limiter.acquire()
    limiter.acquire()  # must wait for the first call to leave the window
    assert clock[0] == pytest.approx(60)


def test_rate_limiter_trusts_remaining_day_header():
    limiter = _RateLimiter(per_minute=100, per_day=3000)
    limiter.update_from_headers({"X-Rate-Limit-Remaining-Day": "0"})
    with pytest.raises(OpenDotaDailyLimitError):
        limiter.acquire()




class _Resp:
    def __init__(self, status, body=None):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body


RECENT = f"/players/{A}/recentMatches"
FULL = f"/players/{A}/matches"
NOW = 1_800_000_000


@pytest.fixture(autouse=True)
def _clean_opendota_cache(monkeypatch):
    monkeypatch.setattr(scouting_api, "_opendota_cache", {})
    monkeypatch.setattr(scouting_api.time, "time", lambda: NOW)
    monkeypatch.setattr(scouting_api, "_two_months_ago_unix", lambda: NOW - 60 * 86400)


def _stub_opendota(monkeypatch, outcomes):
    """Make scouting_api's opendota_get return or raise each outcome of its
    path in turn: outcomes is {path: [outcome, ...]}."""
    calls = []

    def fake_get(path, **kwargs):
        calls.append(path)
        outcome = outcomes[path][calls.count(path) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(scouting_api, "opendota_get", fake_get)
    return calls


def _fetch():
    return scouting_api.fetch_opendota_player_matches(None, A, retry_delay=0)


def _row(mid, start=NOW):
    return {**_od_row(mid, 5), "start_time": start}


@pytest.mark.parametrize("first", [_Resp(500), requests.ConnectionError()])
def test_opendota_matches_retries_once(monkeypatch, first):
    calls = _stub_opendota(monkeypatch, {FULL: [first, _Resp(200, [_row(1)])]})
    matches, status = _fetch()
    assert calls == [FULL, FULL]
    assert status == {"error": None, "fallback": None, "cached_at": None}
    assert [m["match_id"] for m in matches] == [1]


@pytest.mark.parametrize("full, error", [
    ([_Resp(503), _Resp(502)], "HTTP 502"),
    ([_Resp(404, {"error": "x"})], "HTTP 404"),
    ([requests.Timeout()], "timed out"),
])
def test_opendota_matches_falls_back_to_recent_matches(monkeypatch, full, error):
    recent = [{**_row(7), "kills": 3}, _row(8, start=NOW - 90 * 86400)]  # 8 is too old
    calls = _stub_opendota(monkeypatch, {FULL: full, RECENT: [_Resp(200, recent)]})
    matches, status = _fetch()
    assert calls == [FULL] * len(full) + [RECENT]
    assert status == {"error": error, "fallback": "recent", "cached_at": None}
    assert matches == [_row(7)]


def test_opendota_matches_reports_total_failure(monkeypatch):
    _stub_opendota(monkeypatch, {FULL: [requests.Timeout()], RECENT: [_Resp(500)]})
    assert _fetch() == ([], {"error": "timed out", "fallback": None, "cached_at": None})


def test_opendota_daily_limit_skips_recent_matches(monkeypatch):
    calls = _stub_opendota(monkeypatch, {FULL: [OpenDotaDailyLimitError()]})
    assert _fetch() == ([], {"error": "daily limit reached", "fallback": None, "cached_at": None})
    assert calls == [FULL]


def test_opendota_failure_reuses_last_full_history(monkeypatch):
    calls = _stub_opendota(monkeypatch, {FULL: [_Resp(200, [_row(1), _row(2)]), requests.Timeout()]})
    _fetch()
    matches, status = _fetch()
    assert calls == [FULL, FULL]  # no recentMatches: the cache is better
    assert [m["match_id"] for m in matches] == [1, 2]
    assert status["error"] == "timed out" and status["fallback"] == "cache"
    assert status["cached_at"].startswith("2027-01-15")  # NOW, in UTC


def test_opendota_cache_expires(monkeypatch):
    _stub_opendota(monkeypatch, {FULL: [_Resp(200, [_row(1)]), requests.Timeout()], RECENT: [_Resp(200, [])]})
    _fetch()
    monkeypatch.setattr(scouting_api.time, "time", lambda: NOW + scouting_api.OPENDOTA_CACHE_TTL + 1)
    assert _fetch() == ([], {"error": "timed out", "fallback": "recent", "cached_at": None})


def test_fetch_all_reports_progress_and_opendota_status(monkeypatch):
    stratz = {A: [_stratz_match(1, [{"steamAccountId": A, "heroId": 5, "isRadiant": True, "position": 1}])], B: []}
    opendota = {
        A: ([_od_row(2, 8)], {"error": None, "fallback": None, "cached_at": None}),
        B: ([], {"error": "timed out", "fallback": None, "cached_at": None}),
    }
    monkeypatch.setattr(scouting_api, "fetch_player_data", lambda s, sid: (f"p{sid}", stratz[sid]))
    monkeypatch.setattr(scouting_api, "fetch_opendota_player_matches", lambda s, sid: opendota[sid])
    progress = []

    data = scouting_api.fetch_all_scouting_data(
        [{"steam_id": A, "name": "alice"}, {"steam_id": B}],
        on_player=lambda i, total, p: progress.append((i, total, p.get("name"))),
    )

    assert progress == [(0, 2, "alice"), (1, 2, None)]
    assert data["match_sources"][A] == {
        "stratz": 1, "opendota": 1, "opendota_only": 1,
        "opendota_error": None, "opendota_fallback": None, "opendota_cached_at": None,
    }
    assert data["match_sources"][B]["opendota_error"] == "timed out"
