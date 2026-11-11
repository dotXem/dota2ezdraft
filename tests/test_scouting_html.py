import pandas as pd

from scouting_api import drafts_to_html, split_team_game_label, team_games_to_html


def test_split_team_game_label():
    assert split_team_game_label("Anti-Mage (Player One)") == ("Anti-Mage", "Player One")
    assert split_team_game_label("Nature's Prophet") == ("Nature's Prophet", "")


def test_team_games_to_html():
    assert team_games_to_html(pd.DataFrame(), "Rivals") == ""
    games = pd.DataFrame([{
        "Date": "2026-11-01 20:00", "Match ID": 1, "Tournament": "✅", "# Players": 2,
        "Pos 1": "Anti-Mage (One)", "Pos 2": "", "Pos 3": "", "Pos 4": "", "Pos 5": "Axe (<b>Two</b>)",
        "Result": "Won",
    }])
    out = team_games_to_html(games, "Rivals")
    assert "icons/antimage.png" in out and "One" in out and "Won" in out
    assert "&lt;b&gt;Two" in out  # names are escaped


def test_drafts_to_html():
    assert drafts_to_html([], "Rivals") == ""
    draft = {
        "match_id": 1, "date": "2026-11-01 20:00", "radiant": "Rivals", "dire": "Others", "winner": "Rivals",
        "actions": [
            {"order": 0, "type": "Ban", "hero": "Axe", "icon": "", "side": "Radiant", "team": "Rivals"},
            {"order": 1, "type": "Pick", "hero": "Anti-Mage", "icon": "", "side": "Dire", "team": "Others"},
        ],
    }
    out = drafts_to_html([draft], "Rivals")
    assert "icons/antimage.png" in out and "#c62828" in out and "#2e7d32" in out
    assert "repeat(2," in out
    assert "🏆 Rivals" in out and out.index("Rivals") < out.index("Others")

    # The scouted players' team comes first, whatever its name, and the trophy goes to the winner
    out = drafts_to_html([{**draft, "team_side": "Dire", "winner_side": "Dire", "winner": "Others"}], "My name")
    assert out.index("Others") < out.index("Rivals")
    assert "🏆 Others" in out and "🏆 Rivals" not in out
    assert " vs " not in out  # the game line keeps the date only


def test_drafts_without_pick_ban_order():
    from scouting_api import build_scouting_drafts

    players = [{"steamAccountId": i, "isRadiant": True, "heroId": i + 1} for i in range(5)]
    match = {
        "id": 9, "leagueId": 1, "startDateTime": 0, "didRadiantWin": True, "players": players,
        "pickBans": [
            {"heroId": 1, "isPick": False, "isRadiant": True, "order": None},
            {"heroId": 2, "isPick": True, "isRadiant": False, "order": None},
        ],
    }
    (draft,) = build_scouting_drafts({0: [match]}, list(range(5)))
    assert [a["order"] for a in draft["actions"]] == [0, 1]
    assert draft["team_side"] == "Radiant" and draft["winner_side"] == "Radiant"
