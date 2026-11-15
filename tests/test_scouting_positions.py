"""Scouting hero pools by position (offline)."""

from scouting_api import (
    compute_player_hero_stats, extract_player_games, filter_hero_pools, game_positions,
    generate_player_image, hero_stats, possible_positions, roster_positions, team_hero_list,
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
    assert games["Team"].tolist() == [()] * 6  # A's side has only A in these matches
    assert extract_player_games([], A).empty


# A partial OpenDota match with the lineup OpenDota sent (Stratz hero IDs)
CM, ES, SVEN, PUDGE, JUGG = 5, 7, 18, 14, 8
LINEUP_MATCH = {
    "id": 7, "startDateTime": 1_700_000_000, "didRadiantWin": False, "source": "opendota",
    "lineup": {"radiant": [AM, CM, ES, SVEN, PUDGE], "dire": [JUGG, LION, 3, 4, 6]},
    "players": [{"steamAccountId": A, "heroId": ES, "isRadiant": True, "position": None}],
}


def test_extract_player_games_lineup():
    games = extract_player_games([LINEUP_MATCH], A)
    assert games["Position"].tolist() == [0]
    assert games["Team"].tolist() == [("Anti-Mage", "Crystal Maiden", "Earthshaker", "Sven", "Pudge")]
    # Stratz matches list all 10 players: an unknown position takes the lineup from them
    side = [{"steamAccountId": None, "heroId": h, "isRadiant": True, "position": None} for h in (AM, CM, SVEN, PUDGE)]
    stratz = {**LINEUP_MATCH, "lineup": None, "players": LINEUP_MATCH["players"] + side}
    assert set(extract_player_games([stratz], A)["Team"][0]) == set(games["Team"][0])
    # A known position needs no lineup
    known = {**stratz, "players": [{**LINEUP_MATCH["players"][0], "position": "POSITION_4"}] + side}
    assert extract_player_games([known], A)["Team"].tolist() == [()]


HERO_POSITIONS = {
    "Anti-Mage": {1}, "Crystal Maiden": {5}, "Earthshaker": {3, 4, 5},
    "Sven": {1, 2}, "Pudge": {2, 3, 4}, "Axe": {3},
}


def test_possible_positions():
    team = ("Anti-Mage", "Crystal Maiden", "Earthshaker", "Sven", "Pudge")
    # AM 1 and CM 5, so Sven 2: Earthshaker and Pudge share 3 and 4
    assert possible_positions("Earthshaker", team, HERO_POSITIONS) == (3, 4)
    assert possible_positions("Sven", team, HERO_POSITIONS) == (2,)
    # No lineup: the hero's own lists
    assert possible_positions("Earthshaker", (), HERO_POSITIONS) == (3, 4, 5)
    # A lineup fitting no assignment (two pos 1 only heroes): the hero's own lists
    clash = ("Anti-Mage", "Anti-Mage II", "Earthshaker", "Sven", "Pudge")
    assert possible_positions("Earthshaker", clash, {**HERO_POSITIONS, "Anti-Mage II": {1}}) == (3, 4, 5)
    # A teammate in no list takes any position; a hero in no list without lineup has none
    assert possible_positions("Sven", ("Anti-Mage", "X", "Earthshaker", "Sven", "Pudge"), HERO_POSITIONS) == (2,)
    assert possible_positions("X", (), HERO_POSITIONS) == ()


def test_unsure_games_count_at_every_possible_position():
    games = extract_player_games(MATCHES + [LINEUP_MATCH], A)
    at = game_positions(games, HERO_POSITIONS).tolist()
    assert at == [(3,), (3,), (1,), (1,), (5,), (1,), (3, 4)]
    assert game_positions(games).tolist()[-2:] == [(), ()]  # without lists: unknown

    stats = hero_stats(games, hero_positions=HERO_POSITIONS).set_index("Hero")
    assert stats.loc["Anti-Mage", ["Games", "Pos 1"]].tolist() == [2, 2]
    assert stats.loc["Earthshaker", ["Games", "Pos 3", "Pos 4", "Pos 5"]].tolist() == [1, 1, 1, 0]
    # The unsure game shows in both the Pos 3 and the Pos 4 pools
    assert "Earthshaker" in hero_stats(games, [3], HERO_POSITIONS)["Hero"].tolist()
    assert "Earthshaker" in hero_stats(games, [4], HERO_POSITIONS)["Hero"].tolist()
    assert "Earthshaker" not in hero_stats(games, [5], HERO_POSITIONS)["Hero"].tolist()
    # Data fetched before the Team column existed uses the heroes' own lists
    old = games.drop(columns="Team")
    assert hero_stats(old, [5], HERO_POSITIONS)["Hero"].tolist() == ["Lion", "Earthshaker"]


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
    assert left_out == {A: {"other": 3, "unknown": 1, "inferred": 0}}

    # With the Draft lists, the unknown Anti-Mage game counts at Pos 1, and every pool is rebuilt
    pools, left_out = filter_hero_pools(data, players, HERO_POSITIONS)
    assert pools[A]["Games"].sum() == 3
    assert left_out == {A: {"other": 3, "unknown": 0, "inferred": 1}}
    assert pools[B]["Hero"].tolist() == ["Lion"]
    # The filter off rebuilds the whole pools
    pools, left_out = filter_hero_pools(data, players, HERO_POSITIONS, by_position=False)
    assert pools[A]["Games"].sum() == 6 and left_out == {}

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


def test_team_hero_list():
    pools = {A: hero_stats(extract_player_games(MATCHES, A)), B: hero_stats(extract_player_games(MATCHES, B))}
    # Roster order, then most played first, without duplicates (B's Lion is A's too)
    assert team_hero_list(pools, [A, B]) == ["Axe", "Anti-Mage", "Lion"]
    assert team_hero_list(pools, [B, A]) == ["Lion", "Axe", "Anti-Mage"]
    assert team_hero_list(pools, [A, B], top_n=1) == ["Axe", "Lion"]
    assert team_hero_list(pools, [A, B], min_games=2) == ["Axe", "Anti-Mage", "Lion"]  # B: 6 Lion games
    assert team_hero_list(pools, [A], min_games=3) == ["Axe"]
    # Players without data, or with an empty pool, add nothing
    assert team_hero_list({A: hero_stats(extract_player_games([], A))}, [A, 999]) == []
