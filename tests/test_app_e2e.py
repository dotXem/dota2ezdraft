"""Whole app, run in-process with Streamlit's AppTest: `pytest -m e2e` (~2 min).

Needs network: the public data bucket, OpenDota, and Stratz (STRATZ_API_TOKEN in
.env). Accounts go to a throwaway file (see conftest.py) and GCS writes to memory.
"""
import json
from pathlib import Path

import fsspec
import pandas as pd
import pytest
import yaml
from streamlit.testing.v1 import AppTest

import user_manager

pytestmark = pytest.mark.e2e


@pytest.fixture(autouse=True)
def no_gcs_writes(monkeypatch):
    # Scouting uploads its report image through _get_fs() to the public bucket
    monkeypatch.setattr(user_manager, "_get_fs", lambda: fsspec.filesystem("memory"))


def new_session():
    # Absolute: AppTest resolves a relative path against this file's directory
    app = Path(__file__).resolve().parent.parent / "streamlit_app.py"
    at = AppTest.from_file(str(app), default_timeout=600)
    at.run()
    return at


def errors(at):
    return [str(e.value) for e in at.exception] + [e.value for e in at.error]


def by_label(widgets, label):
    return next(w for w in widgets if w.label == label)


def users():
    with open(user_manager.USERS_PATH) as f:
        return yaml.safe_load(f)


def login(at, username, password):
    by_label(at.sidebar.text_input, "Username").set_value(username)
    by_label(at.sidebar.text_input, "Password").set_value(password)
    by_label(at.sidebar.button, "Login").click().run()
    assert any("Connected as" in m.value for m in at.sidebar.markdown), errors(at)


def register_and_login(at, username, password="password123"):
    at.text_input(key="reg_name").set_value(username.title())
    at.text_input(key="reg_username").set_value(username)
    at.text_input(key="reg_password").set_value(password)
    at.text_input(key="reg_password_confirm").set_value(password)
    by_label(at.sidebar.button, "Register").click().run()
    assert any("Account created" in s.value for s in at.success), errors(at)
    login(at, username, password)


def test_startup_and_draft():
    at = new_session()
    assert not errors(at)
    assert [t.label for t in at.tabs] == ["Draft", "My Hero Lists", "Pro Meta"]
    assert any(i.value.startswith("Using ") for i in at.sidebar.info)

    at.text_input(key="enemy_heroes").set_value("am,pudge")
    at.text_input(key="ally_heroes").set_value("Lion")
    at.run()
    df = at.dataframe[0].value
    assert {"Anti-Mage", "Pudge", "Lion"} <= set(df.columns)  # nicknames resolved
    assert not {"Anti-Mage", "Pudge", "Lion"} & set(df.index)  # picked heroes not suggested

    by_label(at.selectbox, "Select filter list").set_value("p1").run()
    assert 0 < len(at.dataframe[0].value) < len(df)

    brackets = at.sidebar.selectbox[1]
    brackets.set_value(brackets.options[-1]).run()
    assert not errors(at)

    by_label(at.button, "Swap Teams").click().run()
    assert at.text_input(key="enemy_heroes").value == "Lion"
    assert at.text_input(key="ally_heroes").value == "am,pudge"


def test_hero_lists():
    at = new_session()
    register_and_login(at, "lister")

    by_label(at.text_input, "List name").set_value("Carries")
    by_label(at.multiselect, "Select heroes").set_value(["Anti-Mage", "Luna", "Spectre"])
    by_label(at.button, "Create list").click().run()
    assert users()["heroes_lists"]["lister"]["Carries"] == ["Anti-Mage", "Luna", "Spectre"]
    assert "Carries" in by_label(at.selectbox, "Select filter list").options

    at.multiselect(key="edit_Carries").set_value(["Anti-Mage", "Luna"])
    at.button(key="save_Carries").click().run()
    assert users()["heroes_lists"]["lister"]["Carries"] == ["Anti-Mage", "Luna"]

    # Last step: AppTest then keeps the deleted list's widgets and can't rerun
    at.button(key="del_Carries").click().run()
    assert "Carries" not in users()["heroes_lists"]["lister"]


def test_password_change_and_logout():
    at = new_session()
    register_and_login(at, "changer")
    at.text_input(key="current_pw").set_value("password123")
    at.text_input(key="new_pw").set_value("newpassword456")
    at.text_input(key="new_pw_confirm").set_value("newpassword456")
    by_label(at.sidebar.button, "Update password").click().run()
    assert any("Password updated" in s.value for s in at.success), errors(at)

    by_label(at.sidebar.button, "Logout").click().run()
    at.run()  # in a browser, the cookie component triggers this rerun
    assert not any("Connected as" in m.value for m in at.sidebar.markdown)

    login(new_session(), "changer", "newpassword456")


def test_pro_meta(needs_stratz):
    at = new_session()
    at.button(key="meta_load_leagues").click().run()
    assert at.selectbox(key="meta_league_sel").options, errors(at)
    at.button(key="meta_fetch_btn").click().run()
    assert any(s.value.startswith("Fetched") for s in at.success), errors(at)
    assert len(at.dataframe) >= 2  # draft suggestions + hero contest stats
    assert at.get("html")  # recent drafts


def pro_team_steam_ids():
    """Five players who were on the same side of a recent pro match."""
    from pro_meta_api import fetch_league_matches, fetch_recent_leagues

    for league in fetch_recent_leagues(count=5):
        for match in fetch_league_matches(league["id"]):
            ids = [p["steamAccountId"] for p in match.get("players") or []
                   if p["isRadiant"] and p.get("steamAccountId")]
            if len(ids) == 5:
                return ids
    pytest.skip("no recent pro match with known players")


def test_scouting(needs_stratz):
    steam_ids = pro_team_steam_ids()
    config = user_manager.load_config()
    user_manager.register_user(config, "scout", "Scout", "password123")
    config["scouting_users"] = ["scout"]
    user_manager.save_config(config)

    at = new_session()
    login(at, "scout", "password123")
    assert "Scouting" in [t.label for t in at.tabs]

    at.text_input(key="scout_new_name").set_value("Pro team")
    at.text_area(key="scout_new_ids").set_value("\n".join(map(str, steam_ids)))
    at.button(key="scout_create_btn").click().run()
    assert "Pro team" in users()["scouting_teams"]["scout"]
    # A browser reruns just the fragment. AppTest reruns the whole app, where
    # st.rerun(scope="fragment") raises, so that's the only error allowed here.
    assert all('scope="fragment"' in e for e in errors(at))
    at.run()

    at.button(key="scout_names_btn").click().run()
    assert not errors(at)
    players = users()["scouting_teams"]["scout"]["Pro team"]["players"]
    assert all(p["name"] for p in players)  # names only, without the full fetch
    assert "scout_data_Pro team" not in at.session_state

    # Rename the first player in the roster table
    at.session_state["scout_roster_Pro team"] = {
        "edited_rows": {0: {"Player": "Renamed"}}, "added_rows": [], "deleted_rows": [],
    }
    at.button(key="scout_save_names_btn").click().run()
    first = users()["scouting_teams"]["scout"]["Pro team"]["players"][0]
    assert first["name"] == "Renamed" and first["name_edited"], errors(at)

    at.button(key="scout_fetch_btn").click().run()
    assert any("fetched successfully" in s.value for s in at.success), errors(at)
    players = users()["scouting_teams"]["scout"]["Pro team"]["players"]
    assert all(p["name"] for p in players)  # names filled in from Stratz
    assert players[0]["name"] == "Renamed"  # a fetch keeps edited names
    assert any("data:image/png;base64" in str(h.proto) for h in at.get("html"))
    assert user_manager._get_fs().exists("heroes-ezdraft/scouting_images/Pro_team_full.png")


def test_config():
    config = user_manager.load_config()
    user_manager.register_user(config, "gridder", "Gridder", "password123")
    config["scouting_users"] = config.get("scouting_users", []) + ["gridder"]
    config.setdefault("scouting_teams", {})["gridder"] = {"Rivals": {"players": [
        {"steam_id": 111, "name": "One"}, {"steam_id": 222, "name": "Two"},
    ]}}
    user_manager.save_config(config)

    at = new_session()
    login(at, "gridder", "password123")
    assert [t.label for t in at.tabs][-1] == "Config"

    def category(name, x, hero_ids):
        return {"category_name": name, "x_position": x, "y_position": 0.0,
                "width": 600.0, "height": 90.0, "hero_ids": hero_ids}

    grid = {"version": 3, "configs": [
        {"config_name": "Mine", "categories": [category("Carries", 0.0, [1, 99999])]},
        {"config_name": "Team", "categories": [category("Mids", 600.0, [2]), category("Supports", 0.0, [26])]},
    ]}
    at.file_uploader(key="config_upload").upload("hero_grid_config.json", yaml.safe_dump(grid).encode()).run()
    assert any("not valid JSON" in e.value for e in at.error)

    at.file_uploader(key="config_upload").upload("hero_grid_config.json", json.dumps(grid).encode()).run()
    assert not errors(at)
    assert any("99999" in w.value for w in at.warning)
    assert at.dataframe[-1].value["Heroes"].tolist() == ["Anti-Mage, #99999"]
    assert any("icons/antimage.png" in str(h.proto) for h in at.get("html"))

    by_label(at.selectbox, "Select grid").set_value(1).run()
    assert not errors(at)
    assert at.dataframe[-1].value["Category"].tolist() == ["Supports", "Mids"]  # in grid order

    # A grid from a scouted team, whose data the Scouting tab would have fetched
    def hero_stats(*rows):
        df = pd.DataFrame(rows, columns=["Hero", "Games", "Wins"])
        return df.assign(Icon="", Winrate=df["Wins"] / df["Games"] * 100, **{"Last Played": "2026-01-01"})

    at.session_state["scout_data_Rivals"] = {
        "player_names": {111: "One", 222: "Two"},
        "player_heroes": {111: hero_stats(("Axe", 3, 1), ("Anti-Mage", 12, 7)), 222: hero_stats(("Lion", 4, 4))},
        "team_games": pd.DataFrame(),
        "drafts": [],
        "fetched_at": "2026-01-01T00:00:00",
    }
    def config_download():
        label = "Download the updated hero_grid_config.json"
        return next(b for b in at.get("download_button") if b.proto.label == label)

    assert config_download().proto.disabled  # nothing new to download yet
    at.button(key="config_add_btn").click().run()
    assert not errors(at)
    grids = by_label(at.selectbox, "Select grid")
    assert len(grids.options) == 3 and grids.value == 2  # the new grid is the one shown
    assert at.dataframe[-1].value["Category"].tolist() == ["One", "12 58%", "3 33%", "Two", "4 100%"]
    assert at.dataframe[-1].value["Heroes"].tolist() == ["", "Anti-Mage", "Axe", "", "Lion"]
    assert not config_download().proto.disabled

    # Adding the same team again asks before replacing its grid
    at.button(key="config_add_btn").click().run()
    assert any("already a grid named 'Rivals'" in w.value for w in at.warning)
    by_label(at.button, "Cancel").click().run()
    assert not errors(at)
    assert not any("already a grid" in w.value for w in at.warning)
    assert len(by_label(at.selectbox, "Select grid").options) == 3

    at.session_state["scout_data_Rivals"]["player_heroes"][222] = hero_stats(("Lion", 5, 5))
    at.button(key="config_add_btn").click().run()
    by_label(at.button, "Replace").click().run()
    assert not errors(at)
    grids = by_label(at.selectbox, "Select grid")
    assert grids.options == ["Mine", "Team", "Rivals"]
    assert grids.value == 2
    assert at.dataframe[-1].value["Category"].tolist()[-1] == "5 100%"
