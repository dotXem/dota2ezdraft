"""Hero grid files (Config tab): parsing, validation and HTML rendering. Offline."""
import copy
import json
import math

import pandas as pd
import pytest

from get_data_from_stratz import HEROES, STRATZ_HERO_TO_ID
from hero_grid import (
    ICON_RATIO, MAX_ICON_WIDTH, _icon_width, dump_hero_grid_config, hero_grid_to_html,
    load_hero_grid_config, scouting_grid_config,
)

GRID = {
    "version": 3,
    "configs": [
        {
            "config_name": "Team",
            "categories": [
                {
                    "category_name": "Mid <premium>",
                    "x_position": 0.0,
                    "y_position": 0.0,
                    "width": 600.0,
                    "height": 90.0,
                    "hero_ids": [1, 2, 99999],  # Anti-Mage, Axe, and an ID no hero has
                },
                {
                    "category_name": "Empty",
                    "x_position": 600.0,
                    "y_position": 120.0,
                    "width": 600.0,
                    "height": 90.0,
                    "hero_ids": [],
                },
            ],
        },
        {"config_name": "No categories", "categories": []},
    ],
}


def test_load_returns_the_file_unchanged():
    assert load_hero_grid_config(json.dumps(GRID)) == GRID
    # Dota writes the file as UTF-8; a BOM added by an editor must not break it
    assert load_hero_grid_config(b"\xef\xbb\xbf" + json.dumps(GRID).encode()) == GRID


def broken(change):
    grid = copy.deepcopy(GRID)
    change(grid)
    return json.dumps(grid)


@pytest.mark.parametrize("raw, message", [
    ("not json", "not valid JSON"),
    ("[]", '"configs"'),
    (broken(lambda g: g.pop("configs")), '"configs"'),
    (broken(lambda g: g["configs"][0].pop("config_name")), '"config_name"'),
    (broken(lambda g: g["configs"][0].pop("categories")), '"categories"'),
    (broken(lambda g: g["configs"][0]["categories"][0].pop("category_name")), '"category_name"'),
    (broken(lambda g: g["configs"][0]["categories"][0].update(width="600")), '"width"'),
    (broken(lambda g: g["configs"][0]["categories"][0].update(hero_ids=["1"])), '"hero_ids"'),
])
def test_load_rejects_other_files(raw, message):
    with pytest.raises(ValueError, match=message):
        load_hero_grid_config(raw)


def test_html():
    html = hero_grid_to_html(GRID["configs"][0])
    assert "icons/antimage.png" in html and 'title="Axe"' in html
    assert "Unknown hero 99999" in html
    assert "Mid &lt;premium&gt;" in html and "<premium>" not in html
    assert hero_grid_to_html(GRID["configs"][1]) == ""


def hero_stats(*rows):
    return pd.DataFrame(rows, columns=["Hero", "Games", "Wins"])


def test_scouting_grid_config():
    many = hero_stats(*[(hero, 20 - i, 1) for i, hero in enumerate(HEROES[:15])])
    grid = scouting_grid_config("Rivals", [
        ("One", hero_stats(("Axe", 3, 1), ("Anti-Mage", 12, 7), ("Unknown (999)", 50, 50))),
        ("Two", pd.DataFrame()),  # private profile: only its name
        ("Three", many),
    ])
    assert grid["config_name"] == "Rivals"

    # Each player starts with an empty category holding the name, 120 under the previous one
    names = [c for c in grid["categories"] if not c["hero_ids"]]
    assert [(c["category_name"], c["x_position"], c["y_position"], c["height"]) for c in names] == [
        ("One", 0, 0, 20), ("Two", 0, 120, 20), ("Three", 0, 240, 20),
    ]
    categories = [c for c in grid["categories"] if c["hero_ids"]]
    assert all(c["width"] == 80 and c["height"] == 80 and len(c["hero_ids"]) == 1 for c in categories)

    # Heroes 20 under the name, most played first, and no category for a hero the app doesn't know
    assert [(c["category_name"], c["x_position"], c["y_position"], c["hero_ids"]) for c in categories[:2]] == [
        ("12 58%", 0, 20, [1]),
        ("3 33%", 80, 20, [2]),
    ]
    # Third player on the third row, limited to the 12 most played heroes
    third = categories[2:]
    assert [c["hero_ids"][0] for c in third] == [STRATZ_HERO_TO_ID[hero] for hero in HEROES[:12]]
    assert [c["x_position"] for c in third] == [80 * i for i in range(12)]
    assert {c["y_position"] for c in third} == {260}
    assert "Three" in hero_grid_to_html(grid)

    # Never lower than 600: that's 5 players, and the rest of a longer roster is left out
    roster = scouting_grid_config("Rivals", [(f"Player {i}", many) for i in range(7)])
    assert max(c["y_position"] + c["height"] for c in roster["categories"]) == 580
    assert [c["category_name"] for c in roster["categories"] if not c["hero_ids"]] == [
        f"Player {i}" for i in range(5)
    ]

    # What gets downloaded is a hero grid file again
    file = {"version": 3, "configs": [grid]}
    assert load_hero_grid_config(dump_hero_grid_config(file)) == file


@pytest.mark.parametrize("n", [1, 3, 7, 16, 40])
@pytest.mark.parametrize("width, height", [(600, 68), (300, 78), (100, 300)])
def test_icons_fit_in_their_category(n, width, height):
    icon_width = _icon_width(n, width, height)
    assert 0 < icon_width <= MAX_ICON_WIDTH
    cols = math.floor(width / icon_width + 1e-9)
    assert math.ceil(n / cols) * icon_width / ICON_RATIO <= height + 1e-9
