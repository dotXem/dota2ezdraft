"""Whole app, run in-process with Streamlit's AppTest: `pytest -m e2e` (~2 min).

Needs network: the public data bucket, OpenDota, and Stratz (STRATZ_API_TOKEN in
.env). Accounts go to a throwaway file (see conftest.py) and GCS writes to memory.
"""
import fsspec
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
    at = AppTest.from_file("streamlit_app.py", default_timeout=600)
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

    at.button(key="scout_fetch_btn").click().run()
    assert any("fetched successfully" in s.value for s in at.success), errors(at)
    players = users()["scouting_teams"]["scout"]["Pro team"]["players"]
    assert all(p["name"] for p in players)  # names filled in from Stratz
    assert any("data:image/png;base64" in str(h.proto) for h in at.get("html"))
    assert user_manager._get_fs().exists("heroes-ezdraft/scouting_images/Pro_team_full.png")
