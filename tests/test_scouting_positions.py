"""Scouting hero pools by position (offline)."""

from scouting_api import (
    compute_player_hero_stats, extract_player_games, filter_hero_pools, generate_player_image,
    hero_stats, roster_positions,
)

A, B = 111, 222
AXE, LION, AM = 2, 26, 1  # Stratz hero IDs


def _match(mid, hero_id, position, radiant_win=True, start=1_700_000_000):
    return {
        "id": mid, "startDateTime": start, "didRadiantWin": radiant_win,
        "players": [
            {"steamAccountId": A, "heroId": hero_id, "isRadiant": True, "position": position},
            {"steamAccountId": B, "heroId": LION, "isRadiant": False, "position": "POSITION_5"},
        ],
    }


MATCHES = [
    _match(1, AXE, "POSITION_3"),
    _match(2, AXE, "POSITION_3", radiant_win=False),
    _match(3, AXE, "POSITION_1"),
    _match(4, AM, "POSITION_1", start=1_700_100_000),
    _match(5, LION, "POSITION_5"),
    _match(6, AM, None),  # OpenDota-only match: no position
]


def test_extract_player_games():
    games = extract_player_games(MATCHES, A)
    assert games["Hero"].tolist() == ["Axe", "Axe", "Axe", "Anti-Mage", "Lion", "Anti-Mage"]
    assert games["Position"].tolist() == [3, 3, 1, 1, 5, 0]
    assert games["Won"].tolist() == [True, False, True, True, True, True]
    assert extract_player_games([], A).empty


def test_hero_stats_all_positions():
    stats = hero_stats(extract_player_games(MATCHES, A)).set_index("Hero")
    assert stats.index.tolist() == ["Axe", "Anti-Mage", "Lion"]  # most played first
    assert stats.loc["Axe", ["Games", "Wins", "Pos 1", "Pos 3"]].tolist() == [3, 2, 1, 2]
    assert stats.loc["Anti-Mage", "Games"] == 2 and stats.loc["Anti-Mage", "Pos 1"] == 1  # one unknown
    assert stats.loc["Axe", "Winrate"] == 66.7
    assert stats.loc["Anti-Mage", "Last Played"] == "2023-11-16"
    assert compute_player_hero_stats(MATCHES, A).equals(hero_stats(extract_player_games(MATCHES, A)))


def test_hero_stats_filtered():
    games = extract_player_games(MATCHES, A)
    carry = hero_stats(games, [1]).set_index("Hero")
    assert carry.index.tolist() == ["Axe", "Anti-Mage"]
    assert carry["Games"].tolist() == [1, 1]  # the unknown Anti-Mage game is left out
    assert hero_stats(games, [1, 3])["Games"].sum() == 4
    assert hero_stats(games, [2]).empty
    assert hero_stats(games, []).equals(hero_stats(games))


def test_roster_positions():
    assert roster_positions({}) == []
    assert roster_positions({"positions": None}) == []
    assert roster_positions({"positions": [3, 1, 1]}) == [1, 3]
    assert roster_positions({"positions": ["5", "4"]}) == [4, 5]  # from the roster editor
    assert roster_positions({"positions": [0, 6, "x"]}) == []


def test_filter_hero_pools():
    data = {
        "player_heroes": {A: hero_stats(extract_player_games(MATCHES, A)), B: "untouched"},
        "player_games": {A: extract_player_games(MATCHES, A), B: extract_player_games(MATCHES, B)},
    }
    players = [{"steam_id": A, "positions": [1]}, {"steam_id": B}]
    pools, left_out = filter_hero_pools(data, players)
    assert pools[A]["Games"].sum() == 2
    assert pools[B] == "untouched"  # no positions: whole pool
    assert left_out == {A: {"other": 3, "unknown": 1}}

    # Data fetched before player_games existed keeps the whole pools
    old = {"player_heroes": data["player_heroes"]}
    pools, left_out = filter_hero_pools(old, players)
    assert pools == old["player_heroes"] and left_out == {}


def test_player_image_with_positions():
    data = {
        "player_names": {A: "One"},
        "player_heroes": {A: hero_stats(extract_player_games(MATCHES, A), [1])},
        "player_positions": {A: [1]},
    }
    assert generate_player_image(data, A).startswith(b"\x89PNG")
