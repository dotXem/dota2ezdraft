"""Draft scoring (hero_suggestion.py) on a bundled snapshot. Offline."""
import contextlib

import numpy as np
import pandas as pd
import pytest
import yaml

from hero_suggestion import (
    compute_counter_scores,
    compute_synergy_scores,
    create_winrate_enemy_synergy_dfs,
    identify_exceptional_interactions,
    suggest_heroes_from_ally_and_enemy,
)

ENEMIES, ALLIES = ["Faceless Void", "Techies"], ["Lich"]


@pytest.fixture(scope="module")
def scores():
    with open("2024-09-21.yaml") as f:
        data = yaml.safe_load(f)
    winrates, enemy, ally = create_winrate_enemy_synergy_dfs(data)
    return {
        "winrates": winrates,
        "enemy": enemy,
        "ally": ally,
        "counters": compute_counter_scores(winrates, enemy),
        "synergies": compute_synergy_scores(winrates, ally),
    }


def test_pairwise_winrates_are_symmetrized(scores):
    vs = (scores["enemy"] + scores["enemy"].T).values
    np.testing.assert_allclose(vs[~np.isnan(vs)], 1)  # A's winrate vs B + B's vs A
    np.testing.assert_allclose(scores["ally"].values, scores["ally"].T.values)


def test_a_hero_has_no_score_with_itself(scores):
    assert np.isnan(np.diag(scores["counters"].values)).all()
    assert np.isnan(np.diag(scores["synergies"].values)).all()


def test_exceptional_interactions(scores):
    # pandas 3 always uses Copy-on-Write, where writing through df.values raises
    # (fixed in 1345ba8). Turn it on here so pandas 2 catches that too.
    cow = (pd.option_context("mode.copy_on_write", True)
           if int(pd.__version__.split(".")[0]) < 3 else contextlib.nullcontext())
    with cow:
        exceptional = identify_exceptional_interactions(scores["counters"])
    values = exceptional.values
    assert set(np.unique(values)) <= {-1, 0, 1}
    assert (np.diag(values) == 0).all()
    assert 0.05 < (values == 1).mean() < 0.15  # top 10% of pairs
    assert 0.05 < (values == -1).mean() < 0.15  # bottom 10%


def test_suggestions(scores):
    counters, synergies = scores["counters"], scores["synergies"]
    df = suggest_heroes_from_ally_and_enemy(
        scores["winrates"], counters, synergies,
        identify_exceptional_interactions(counters), identify_exceptional_interactions(synergies),
        ENEMIES, ALLIES,
    )
    assert not set(ENEMIES) & set(df.index)
    # Allies come back with a NaN score; the app drops every picked hero before display
    candidates = df.drop(index=ALLIES)
    np.testing.assert_allclose(candidates["score"], candidates["score_enemy"] + candidates["score_ally"])
    hero = candidates.index[0]
    assert candidates.loc[hero, "Faceless Void"] == pytest.approx(counters.loc[hero, "Faceless Void"])
    assert candidates.loc[hero, "Lich"] == pytest.approx(synergies.loc[hero, "Lich"])
    assert df["relevance"].between(0, 3).all()
