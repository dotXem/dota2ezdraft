"""OpenDota rate limiter and the Stratz/OpenDota match merge used by Scouting (offline)."""

import pytest

import opendota_api
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
