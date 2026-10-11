"""Daily snapshot assembly and upload, with Stratz and GCS stubbed out. Offline."""
import datetime
from types import SimpleNamespace

import pytest
import yaml

import get_data_from_stratz as stratz

HEROES = stratz.HEROES
BRACKET = "[DIVINE,IMMORTAL]"


def matchups(hero, winrate=0.5):
    others = {h: winrate for h in HEROES if h != hero}
    return {"matchup_winrate": others, "synergy_winrate": others, "winrate": winrate}


def full_snapshot(winrate):
    return {h: {**matchups(h, winrate), "winrate_brackets": {BRACKET: winrate},
                "positions": ["POSITION_5"]} for h in HEROES}


@pytest.fixture
def stub_stratz(monkeypatch):
    """Make Stratz answer for every hero except `missing`."""
    def stub(missing=()):
        monkeypatch.setattr(stratz, "get_matchup_data_from_stratz",
                            lambda session: {h: matchups(h) for h in HEROES if h not in missing})
        monkeypatch.setattr(stratz, "get_winrates_per_bracket",
                            lambda session: {BRACKET: {h: 0.52 for h in HEROES}})
        monkeypatch.setattr(stratz, "get_hero_per_position",
                            lambda session: {h: ["POSITION_1"] for h in HEROES})
    return stub


def test_complete_fetch(stub_stratz):
    stub_stratz()
    data = stratz.get_data_from_stratz()
    assert set(data) == set(HEROES)
    assert data["Lion"]["winrate_brackets"] == {BRACKET: 0.52}
    assert data["Lion"]["positions"] == ["POSITION_1"]


def test_missing_hero_reuses_previous_snapshot(stub_stratz):
    stub_stratz(missing=["Queen of Pain"])
    data = stratz.get_data_from_stratz(fallback=full_snapshot(0.4))
    qop = data["Queen of Pain"]
    assert qop["winrate"] == 0.4 and qop["matchup_winrate"]["Lion"] == 0.4
    # bracket winrates and positions come from today's queries
    assert qop["winrate_brackets"] == {BRACKET: 0.52}
    assert qop["positions"] == ["POSITION_1"]
    assert data["Lion"]["winrate"] == 0.5


def test_too_many_missing_heroes_are_not_filled(stub_stratz):
    missing = HEROES[: stratz.MAX_FALLBACK_HEROES + 1]
    stub_stratz(missing=missing)
    data = stratz.get_data_from_stratz(fallback=full_snapshot(0.4))
    assert len(data) == len(HEROES) - len(missing)


def test_hero_absent_from_previous_snapshot_stays_missing(stub_stratz):
    stub_stratz(missing=["Queen of Pain"])
    previous = full_snapshot(0.4)
    del previous["Queen of Pain"]
    assert "Queen of Pain" not in stratz.get_data_from_stratz(fallback=previous)


class FakeBucket:
    def __init__(self, files):
        self.files, self.uploaded = files, {}

    def list_blobs(self, prefix):
        return [SimpleNamespace(name=name, download_as_text=lambda text=text: text)
                for name, text in self.files.items() if name.startswith(prefix)]

    def blob(self, name):
        return SimpleNamespace(upload_from_string=lambda text, content_type: self.uploaded.__setitem__(name, text))


@pytest.fixture
def job(monkeypatch):
    pytest.importorskip("google.cloud.storage")
    import fetch_and_upload

    bucket = FakeBucket({
        "data/2026-10-07.yaml": "not: read",
        "data/2026-10-09.yaml": yaml.dump(full_snapshot(0.4)),
        "icons/lion.png": "",
    })
    client = SimpleNamespace(bucket=lambda name: bucket)
    monkeypatch.setattr(fetch_and_upload, "storage", SimpleNamespace(Client=lambda: client))
    return fetch_and_upload.main, bucket


def test_job_fills_from_latest_snapshot_and_uploads(job, stub_stratz):
    main, bucket = job
    stub_stratz(missing=["Queen of Pain"])
    main()
    uploaded = yaml.safe_load(bucket.uploaded[f"data/{datetime.date.today()}.yaml"])
    assert set(uploaded) == set(HEROES)
    assert uploaded["Queen of Pain"]["winrate"] == 0.4


def test_job_fails_without_uploading_when_heroes_are_missing(job, stub_stratz):
    main, bucket = job
    stub_stratz(missing=HEROES[: stratz.MAX_FALLBACK_HEROES + 1])
    with pytest.raises(RuntimeError, match="Only fetched"):
        main()
    assert not bucket.uploaded
