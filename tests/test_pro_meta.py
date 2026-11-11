"""Pro Meta positions: OpenDota matches get their positions from Stratz. Offline."""
import re

import pytest
import requests

import pro_meta_api

RADIANT = [1, 53, 2, 3, 26]  # Anti-Mage, Nature's Prophet, ...
DIRE = [4, 5, 6, 7, 8]


def opendota_match(match_id):
    """A match as _fetch_via_opendota returns it: no positions."""
    return {
        "id": match_id,
        "didRadiantWin": True,
        "pickBans": [{"isPick": True, "heroId": h, "isRadiant": h in RADIANT}
                     for h in RADIANT + DIRE],
        "players": [{"heroId": h, "isRadiant": h in RADIANT, "position": None,
                     "steamAccountId": None} for h in RADIANT + DIRE],
    }


def stratz_match(match_id):
    """Stratz's answer to match(id:): positions 1-5 in hero order on each side."""
    return {"id": match_id, "players": [
        {"heroId": h, "position": f"POSITION_{i % 5 + 1}"}
        for i, h in enumerate(RADIANT + DIRE)
    ]}


@pytest.fixture
def stratz(monkeypatch):
    """Stub Stratz: no league record, and per-match answers for `known` match IDs."""
    calls = []

    def stub(known):
        def gql(query):
            calls.append(query)
            ids = map(int, re.findall(r"match\(id: (\d+)\)", query))
            return {"data": {f"m{i}": stratz_match(i) if i in known else None for i in ids}}
        monkeypatch.setattr(pro_meta_api, "_fetch_via_stratz", lambda league_id: None)
        monkeypatch.setattr(pro_meta_api, "_gql", gql)
        return calls
    return stub


def fetch(monkeypatch, match_ids):
    monkeypatch.setattr(pro_meta_api, "_fetch_via_opendota",
                        lambda league_id: [opendota_match(i) for i in match_ids])
    return pro_meta_api.fetch_league_matches(1)


def test_positions_from_stratz(monkeypatch, stratz):
    stratz(known={10, 11})
    matches = fetch(monkeypatch, [10, 11, 12])  # Stratz doesn't have match 12
    assert [p["position"] for p in matches[0]["players"][:5]] == pro_meta_api.POSITIONS
    assert all(p["position"] is None for p in matches[2]["players"])
    assert pro_meta_api.count_matches_with_positions(matches) == 2

    stats, total = pro_meta_api.compute_hero_stats(matches)
    prophet = stats.set_index("Hero").loc["Nature's Prophet"]
    assert (total, prophet["Picks"], prophet["Pos 2"], prophet["Pos 1"]) == (3, 3, 2, 0)


def test_many_matches_take_several_requests(monkeypatch, stratz):
    monkeypatch.setattr(pro_meta_api, "_POSITIONS_PER_REQUEST", 2)
    calls = stratz(known={10, 11, 12})
    matches = fetch(monkeypatch, [10, 11, 12])
    assert len(calls) == 2
    assert pro_meta_api.count_matches_with_positions(matches) == 3


def test_stratz_down_keeps_matches(monkeypatch, stratz):
    stratz(known=set())

    def down(query):
        raise requests.ConnectionError("down")
    monkeypatch.setattr(pro_meta_api, "_gql", down)
    matches = fetch(monkeypatch, [10, 11])
    assert len(matches) == 2
    assert pro_meta_api.count_matches_with_positions(matches) == 0
