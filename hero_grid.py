"""Config tab backend: reads Dota 2 hero grid files (hero_grid_config.json) and renders them."""

import html
import json
import math

from get_data_from_stratz import STRATZ_HERO_TO_ID, STRATZ_ID_TO_HERO
from scouting_api import get_hero_icon_url

# Layout constants, in the file's own units (the ones of x_position, width, ...)
TITLE_HEIGHT = 22
MAX_ICON_WIDTH = 80
ICON_RATIO = 16 / 9  # the icons are 256x144

# Grids built from a scouted team: a name category per player, then one single-hero category per hero
SCOUT_NAME_HEIGHT = 20.0
SCOUT_CATEGORY_WIDTH = 80.0
SCOUT_CATEGORY_HEIGHT = 80.0
SCOUT_ROW_STEP = 120.0  # from a player's name to the next one's, which leaves a gap under the heroes
SCOUT_MAX_HEROES = 12
# No category may go lower than this (y_position + height), which leaves room for 5 players
SCOUT_MAX_HEIGHT = 600.0
SCOUT_MAX_PLAYERS = int((SCOUT_MAX_HEIGHT - SCOUT_NAME_HEIGHT - SCOUT_CATEGORY_HEIGHT) // SCOUT_ROW_STEP) + 1


def _is_number(value):
    # json.loads accepts NaN and Infinity, which would break the layout and the written file
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def load_hero_grid_config(raw):
    """Parse and check the content (bytes or str) of a hero_grid_config.json.

    Returns the parsed file as is, unknown keys included, so that it can be
    written back without losing anything. Raises ValueError with a readable
    message when it isn't a hero grid file.
    """
    try:
        grid = json.loads(raw)
    except ValueError as e:
        raise ValueError(f"not valid JSON ({e})")

    if not isinstance(grid, dict) or not isinstance(grid.get("configs"), list):
        raise ValueError('no "configs" list')

    for config in grid["configs"]:
        if not isinstance(config, dict) or not isinstance(config.get("config_name"), str):
            raise ValueError('a config has no "config_name"')
        name = config["config_name"]
        if not isinstance(config.get("categories"), list):
            raise ValueError(f'config "{name}" has no "categories" list')

        for category in config["categories"]:
            if not isinstance(category, dict) or not isinstance(category.get("category_name"), str):
                raise ValueError(f'a category of config "{name}" has no "category_name"')
            where = f'category "{category["category_name"]}" of config "{name}"'
            for key in ("x_position", "y_position", "width", "height"):
                if not _is_number(category.get(key)):
                    raise ValueError(f'{where} has no numeric "{key}"')
            hero_ids = category.get("hero_ids")
            if not isinstance(hero_ids, list) or not all(type(i) is int for i in hero_ids):
                raise ValueError(f'{where} has no "hero_ids" list of integers')

    return grid


def dump_hero_grid_config(grid):
    """Serialize a hero grid file, tab-indented like the ones Dota writes."""
    return json.dumps(grid, indent="\t")


def scouting_grid_config(config_name, players):
    """Build a grid config from a scouted team: a row per player, a category per hero.

    players holds a (name, hero stats) pair per player, in roster order; the
    stats are the DataFrames made by scouting_api.compute_player_hero_stats.
    A row starts with an empty category named after the player. Under it come
    the player's SCOUT_MAX_HEROES most played heroes, each alone in a category
    named "<games> <winrate>%". A player without data only gets the name.
    Only the first SCOUT_MAX_PLAYERS players are used, so that the grid stays
    within SCOUT_MAX_HEIGHT.
    """
    categories = []
    for row, (name, heroes) in enumerate(players[:SCOUT_MAX_PLAYERS]):
        y = row * SCOUT_ROW_STEP
        categories.append({
            "category_name": name,
            "x_position": 0.0,
            "y_position": y,
            "width": SCOUT_MAX_HEROES * SCOUT_CATEGORY_WIDTH,
            "height": SCOUT_NAME_HEIGHT,
            "hero_ids": [],
        })
        if heroes.empty:
            continue
        heroes = heroes[heroes["Hero"].isin(STRATZ_HERO_TO_ID)]
        top = heroes.sort_values(["Games", "Wins"], ascending=False, kind="stable").head(SCOUT_MAX_HEROES)
        for col, hero in enumerate(top.itertuples()):
            games, wins = int(hero.Games), int(hero.Wins)
            categories.append({
                "category_name": f"{games} {wins / games:.0%}",
                "x_position": col * SCOUT_CATEGORY_WIDTH,
                "y_position": y + SCOUT_NAME_HEIGHT,
                "width": SCOUT_CATEGORY_WIDTH,
                "height": SCOUT_CATEGORY_HEIGHT,
                "hero_ids": [STRATZ_HERO_TO_ID[hero.Hero]],
            })
    return {"config_name": config_name, "categories": categories}


def _icon_width(n, width, height):
    """Widest icon that lets n of them fit, wrapping, in a width x height box."""
    best = 0
    for cols in range(1, n + 1):
        rows = math.ceil(n / cols)
        best = max(best, min(width / cols, height / rows * ICON_RATIO))
    return min(best, MAX_ICON_WIDTH)


def hero_grid_to_html(grid_config):
    """Render one config of a hero grid file as HTML, laid out as in game.

    Every size is relative to the container's width, so the grid scales with the page.
    """
    categories = grid_config["categories"]
    total_w = max((c["x_position"] + c["width"] for c in categories), default=0)
    total_h = max((c["y_position"] + c["height"] for c in categories), default=0)
    if total_w <= 0 or total_h <= 0:
        return ""

    def _cqw(units):
        return f"{units / total_w * 100:.3f}cqw"

    def _hero(hero_id, width_pct):
        hero = STRATZ_ID_TO_HERO.get(hero_id)
        icon = get_hero_icon_url(hero) if hero else None
        size = f"width:{width_pct:.2f}%;aspect-ratio:16/9;box-sizing:border-box;"
        if icon:
            return (
                f'<img src="{icon}" title="{html.escape(hero)}" '
                f'style="{size}padding:{_cqw(1)};border-radius:{_cqw(3)};">'
            )
        return (
            f'<div title="{html.escape(hero or f"Unknown hero {hero_id}")}" '
            f'style="{size}border:{_cqw(1)} solid #1a1a2e;background:#555;color:#eee;'
            f'font-size:{_cqw(11)};display:flex;align-items:center;justify-content:center;">'
            f'{hero_id}</div>'
        )

    boxes = ""
    for category in categories:
        hero_ids = category["hero_ids"]
        width = max(category["width"], 1)
        # A category can be lower than a title, like the player names of a scouted team's grid
        title_height = min(TITLE_HEIGHT, max(category["height"], 0))
        icons_height = max(category["height"] - TITLE_HEIGHT, 1)
        # Rounded down, so that a full row never wraps
        width_pct = math.floor(_icon_width(len(hero_ids), width, icons_height) / width * 10000) / 100
        boxes += (
            f'<div style="position:absolute;overflow:hidden;'
            f'left:{category["x_position"] / total_w * 100:.3f}%;'
            f'top:{category["y_position"] / total_h * 100:.3f}%;'
            f'width:{category["width"] / total_w * 100:.3f}%;'
            f'height:{category["height"] / total_h * 100:.3f}%;'
            f'background:#1a1a2e;box-shadow:inset 0 0 0 1px #444;border-radius:{_cqw(4)};">'
            f'<div style="height:{_cqw(title_height)};line-height:{_cqw(title_height)};'
            f'font-size:{_cqw(13)};padding:0 {_cqw(6)};color:#eee;font-weight:bold;'
            f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">'
            f'{html.escape(category["category_name"])}</div>'
            f'<div style="display:flex;flex-wrap:wrap;align-content:flex-start;">'
            + "".join(_hero(hero_id, width_pct) for hero_id in hero_ids)
            + '</div></div>'
        )

    return (
        f'<div style="position:relative;width:100%;aspect-ratio:{total_w:.3f}/{total_h:.3f};'
        f'container-type:inline-size;">{boxes}</div>'
    )
