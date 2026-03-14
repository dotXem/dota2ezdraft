"""Stratz API integration for player and team scouting."""

import io
import json
import time
import datetime
import requests
import pandas as pd
from get_data_from_stratz import (
    STRATZ_API_URL, HEADERS, STRATZ_ID_TO_HERO, STRATZ_HERO_TO_ID
)

STEAM_ID_64_BASE = 76561197960265728


def normalize_steam_id(raw):
    """Convert a Steam ID string (32-bit or 64-bit) to 32-bit account ID."""
    steam_id = int(str(raw).strip())
    if steam_id > STEAM_ID_64_BASE:
        steam_id = steam_id - STEAM_ID_64_BASE
    return steam_id


def _two_months_ago_unix():
    now = datetime.datetime.utcnow()
    return int((now - datetime.timedelta(days=60)).timestamp())


def _fetch_graphql(session, query):
    """Execute a GraphQL query against Stratz API with rate limiting."""
    payload = json.dumps({"query": query})
    time.sleep(1)
    resp = session.post(STRATZ_API_URL, headers=HEADERS, data=payload)
    if resp.status_code != 200:
        return None
    return resp.json()


def fetch_player_data(session, steam_id):
    """
    Fetch player name and paginated matches from the past 2 months.
    Returns (player_name, matches_list).
    """
    account_id = normalize_steam_id(steam_id)
    start_ts = _two_months_ago_unix()

    # First query: name + first page of matches
    query = """
    {
      player(steamAccountId: %d) {
        steamAccount {
          name
          proSteamAccount { name }
        }
        matches(request: {startDateTime: %d, take: 100, skip: 0}) {
          id
          startDateTime
          didRadiantWin
          lobbyType
          leagueId
          radiantTeam { name }
          direTeam { name }
          pickBans {
            isPick
            heroId
            order
            isRadiant
          }
          players {
            steamAccountId
            heroId
            isRadiant
            position
          }
        }
      }
    }
    """ % (account_id, start_ts)

    data = _fetch_graphql(session, query)
    if not data:
        return str(steam_id), []

    try:
        player = data["data"]["player"]
        acct = player.get("steamAccount") or {}
        pro = acct.get("proSteamAccount")
        name = (pro.get("name") if pro else None) or acct.get("name") or str(steam_id)
        matches = player.get("matches") or []
    except (KeyError, TypeError):
        return str(steam_id), []

    # Paginate if first page had 100 matches
    skip = 100
    while len(matches) == skip:
        page_query = """
        {
          player(steamAccountId: %d) {
            matches(request: {startDateTime: %d, take: 100, skip: %d}) {
              id
              startDateTime
              didRadiantWin
              lobbyType
              leagueId
              radiantTeam { name }
              direTeam { name }
              pickBans {
                isPick
                heroId
                order
                isRadiant
              }
              players {
                steamAccountId
                heroId
                isRadiant
                position
              }
            }
          }
        }
        """ % (account_id, start_ts, skip)

        page_data = _fetch_graphql(session, page_query)
        if not page_data:
            break
        try:
            page_matches = page_data["data"]["player"].get("matches") or []
        except (KeyError, TypeError):
            break
        if not page_matches:
            break
        matches.extend(page_matches)
        skip += 100

    return name, matches


def compute_player_hero_stats(matches, steam_id):
    """Compute per-hero stats from match data. Returns a DataFrame."""
    hero_stats = {}

    for match in matches:
        ts = match.get("startDateTime", 0)
        radiant_win = match.get("didRadiantWin")
        for p in match.get("players") or []:
            if p["steamAccountId"] != steam_id:
                continue
            hid = p["heroId"]
            won = (p["isRadiant"] == radiant_win) if radiant_win is not None else False

            entry = hero_stats.setdefault(hid, {"games": 0, "wins": 0, "last_played": 0})
            entry["games"] += 1
            if won:
                entry["wins"] += 1
            entry["last_played"] = max(entry["last_played"], ts)
            break

    rows = []
    for hid, s in hero_stats.items():
        hero_name = STRATZ_ID_TO_HERO.get(hid, f"Unknown ({hid})")
        winrate = round(s["wins"] / s["games"] * 100, 1) if s["games"] else 0.0
        last_dt = datetime.datetime.utcfromtimestamp(s["last_played"])
        rows.append({
            "Icon": get_hero_icon_url(hero_name) or "",
            "Hero": hero_name,
            "Games": s["games"],
            "Wins": s["wins"],
            "Winrate": winrate,
            "Last Played": last_dt.strftime("%Y-%m-%d"),
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("Games", ascending=False).reset_index(drop=True)
    return df


def find_team_games(all_player_matches, steam_ids, player_names):
    """
    Find games where multiple team members played on the same side.
    Returns DataFrame sorted: tournament first, then team member count desc, then date desc.
    """
    matches_by_id = {}
    for sid, matches in all_player_matches.items():
        for m in matches:
            mid = m["id"]
            if mid not in matches_by_id:
                matches_by_id[mid] = m

    steam_set = set(steam_ids)
    rows = []

    for mid, match in matches_by_id.items():
        team_in_match = []
        for p in match.get("players") or []:
            if p["steamAccountId"] in steam_set:
                team_in_match.append(p)

        if len(team_in_match) < 2:
            continue

        # Group by side, pick the side with the most team members
        radiant = [p for p in team_in_match if p["isRadiant"]]
        dire = [p for p in team_in_match if not p["isRadiant"]]
        if len(radiant) >= len(dire):
            side_players = radiant
            main_side_radiant = True
        else:
            side_players = dire
            main_side_radiant = False

        if len(side_players) < 2:
            continue

        radiant_win = match.get("didRadiantWin")
        if radiant_win is not None:
            won = main_side_radiant == radiant_win
        else:
            won = None

        is_tournament = bool(match.get("leagueId"))
        ts = match.get("startDateTime", 0)
        dt = datetime.datetime.utcfromtimestamp(ts)

        result = "Won" if won else ("Lost" if won is False else "?")

        # Build per-position columns
        pos_cols = {"Pos 1": "", "Pos 2": "", "Pos 3": "", "Pos 4": "", "Pos 5": ""}
        pos_map = {
            "POSITION_1": "Pos 1", "POSITION_2": "Pos 2", "POSITION_3": "Pos 3",
            "POSITION_4": "Pos 4", "POSITION_5": "Pos 5",
        }
        for p in side_players:
            hero = STRATZ_ID_TO_HERO.get(p["heroId"], "?")
            pname = player_names.get(p["steamAccountId"], "")
            label = f"{hero} ({pname})" if pname else hero
            pos_key = pos_map.get(p.get("position"), "")
            if pos_key:
                pos_cols[pos_key] = label
            else:
                # Assign to first empty slot if position unknown
                for k in pos_cols:
                    if not pos_cols[k]:
                        pos_cols[k] = label
                        break

        rows.append({
            "Date": dt.strftime("%Y-%m-%d %H:%M"),
            "Match ID": mid,
            "Tournament": "✅" if is_tournament else "",
            "# Players": len(side_players),
            **pos_cols,
            "Result": result,
            "_ts": ts,
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df["_tour"] = df["Tournament"].apply(lambda x: 1 if x else 0)
        df = df.sort_values(
            ["_tour", "# Players", "_ts"],
            ascending=[False, False, False],
        ).reset_index(drop=True)
        df = df.drop(columns=["_tour", "_ts"])
    return df


def build_scouting_drafts(all_player_matches, steam_ids):
    """
    Find tournament games where all 5 players played on the same side
    and build draft dicts (same format as pro_meta_api.build_draft_table).
    """
    matches_by_id = {}
    for sid, matches in all_player_matches.items():
        for m in matches:
            mid = m["id"]
            if mid not in matches_by_id:
                matches_by_id[mid] = m

    steam_set = set(steam_ids)
    drafts = []

    for mid, match in matches_by_id.items():
        if not match.get("leagueId"):
            continue
        if not match.get("pickBans"):
            continue

        team_in_match = []
        for p in match.get("players") or []:
            if p["steamAccountId"] in steam_set:
                team_in_match.append(p)

        radiant = [p for p in team_in_match if p["isRadiant"]]
        dire = [p for p in team_in_match if not p["isRadiant"]]
        if len(radiant) >= len(dire):
            side_players = radiant
        else:
            side_players = dire

        if len(side_players) < 5:
            continue

        ts = match.get("startDateTime", 0)
        dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
        rad_team = (match.get("radiantTeam") or {}).get("name", "Radiant")
        dire_team = (match.get("direTeam") or {}).get("name", "Dire")
        rad_win = match.get("didRadiantWin")
        winner = rad_team if rad_win else dire_team

        pick_bans = sorted(match.get("pickBans") or [], key=lambda x: x.get("order", 0))
        actions = []
        for pb in pick_bans:
            hid = pb.get("heroId")
            hero_name = STRATZ_ID_TO_HERO.get(hid, f"?{hid}")
            icon = get_hero_icon_url(hero_name) or ""
            actions.append({
                "order": pb["order"],
                "type": "Pick" if pb["isPick"] else "Ban",
                "hero": hero_name,
                "icon": icon,
                "side": "Radiant" if pb["isRadiant"] else "Dire",
                "team": rad_team if pb["isRadiant"] else dire_team,
            })

        drafts.append({
            "match_id": mid,
            "date": dt.strftime("%Y-%m-%d %H:%M"),
            "radiant": rad_team,
            "dire": dire_team,
            "winner": winner,
            "actions": actions,
        })

    drafts.sort(key=lambda d: d["date"], reverse=True)
    return drafts


def fetch_all_scouting_data(team_players):
    """
    Fetch complete scouting data for a team.
    Returns dict with player_names, player_heroes, team_games, drafts, and fetched_at.
    """
    session = requests.Session()
    steam_ids = [normalize_steam_id(p["steam_id"]) for p in team_players]

    player_names = {}
    player_heroes = {}
    all_matches = {}

    for sid in steam_ids:
        name, matches = fetch_player_data(session, sid)
        player_names[sid] = name
        all_matches[sid] = matches

    # Build a merged match pool per player: their own matches + matches where
    # they appear in other players' data (covers private/partial profiles).
    merged_matches = {sid: list(ms) for sid, ms in all_matches.items()}
    seen_ids = {sid: {m["id"] for m in ms} for sid, ms in all_matches.items()}

    for sid, matches in all_matches.items():
        for m in matches:
            for p in m.get("players") or []:
                psid = p["steamAccountId"]
                if psid in seen_ids and m["id"] not in seen_ids[psid]:
                    merged_matches[psid].append(m)
                    seen_ids[psid].add(m["id"])

    for sid in steam_ids:
        player_heroes[sid] = compute_player_hero_stats(merged_matches[sid], sid)

    team_games = find_team_games(all_matches, steam_ids, player_names)
    drafts = build_scouting_drafts(all_matches, steam_ids)

    return {
        "player_names": player_names,
        "player_heroes": player_heroes,
        "team_games": team_games,
        "drafts": drafts,
        "fetched_at": datetime.datetime.utcnow().isoformat(),
    }


def generate_player_markdown(data, steam_id):
    """Generate markdown for a single player's hero pool."""
    sid = normalize_steam_id(steam_id)
    name = data["player_names"].get(sid, str(sid))
    dotabuff = f"https://www.dotabuff.com/players/{sid}"
    stratz = f"https://stratz.com/players/{sid}"
    opendota = f"https://www.opendota.com/players/{sid}"

    lines = [f"### {name}"]
    lines.append(f"[Dotabuff]({dotabuff}) | [Stratz]({stratz}) | [OpenDota]({opendota})")
    lines.append("")

    df = data.get("player_heroes", {}).get(sid, pd.DataFrame())
    if df.empty:
        lines.append("*No matches found — profile may be private.*")
    else:
        lines.append("| Hero | Games | Wins | WR% | Last Played |")
        lines.append("|------|-------|------|-----|-------------|")
        for _, row in df.iterrows():
            lines.append(
                f"| {row['Hero']} | {int(row['Games'])} | {int(row['Wins'])} | {row['Winrate']:.1f}% | {row['Last Played']} |"
            )
    lines.append("")
    return "\n".join(lines)


def generate_team_games_markdown(data, team_name):
    """Generate markdown for team games section."""
    team_games = data.get("team_games", pd.DataFrame())
    lines = [f"## Team Games — {team_name}", ""]

    if team_games.empty:
        lines.append("*No games found where team members played together.*")
    else:
        lines.append(f"*{len(team_games)} games with 2+ members on the same side.*")
        lines.append("")
        lines.append("| Date | Match ID | Tour. | # | Pos 1 | Pos 2 | Pos 3 | Pos 4 | Pos 5 | Result |")
        lines.append("|------|----------|-------|---|-------|-------|-------|-------|-------|--------|")
        for _, row in team_games.iterrows():
            lines.append(
                f"| {row['Date']} | {row['Match ID']} | {row['Tournament']} | "
                f"{int(row['# Players'])} | {row['Pos 1']} | {row['Pos 2']} | {row['Pos 3']} | "
                f"{row['Pos 4']} | {row['Pos 5']} | {row['Result']} |"
            )
    lines.append("")
    return "\n".join(lines)


def generate_scouting_markdown(data, team_name, players):
    """Generate full markdown scouting report."""
    parts = [f"# Scouting Report: {team_name}", ""]
    parts.append(f"*Fetched: {data.get('fetched_at', '?')} UTC*")
    parts.append("")
    parts.append("## Player Hero Pools (Past 2 Months)")
    parts.append("")
    for p in players:
        parts.append(generate_player_markdown(data, p["steam_id"]))
    parts.append(generate_team_games_markdown(data, team_name))
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Image generation with hero icons
# ---------------------------------------------------------------------------

_hero_icon_cache = {}
_hero_shortnames = None

HERO_ICON_CDN = "https://storage.googleapis.com/heroes-ezdraft/icons/{slug}.png"


def get_hero_icon_url(hero_name):
    """Return CDN icon URL for a hero name, or None."""
    shortnames = _get_hero_shortnames()
    hero_id = STRATZ_HERO_TO_ID.get(hero_name)
    slug = shortnames.get(hero_id) if hero_id else None
    if slug:
        return HERO_ICON_CDN.format(slug=slug)
    return None


def _get_hero_shortnames():
    """Fetch hero id→shortName mapping from Stratz (cached)."""
    global _hero_shortnames
    if _hero_shortnames is not None:
        return _hero_shortnames
    try:
        q = '{constants { heroes { id shortName } }}'
        payload = json.dumps({"query": q})
        r = requests.post(STRATZ_API_URL, headers=HEADERS, data=payload, timeout=10)
        heroes = r.json()["data"]["constants"]["heroes"]
        _hero_shortnames = {h["id"]: h["shortName"] for h in heroes}
    except Exception:
        _hero_shortnames = {}
    return _hero_shortnames


def _get_hero_icon(hero_name, size=32):
    """Download and cache a hero icon as a PIL Image."""
    from PIL import Image

    cache_key = (hero_name, size)
    if cache_key in _hero_icon_cache:
        return _hero_icon_cache[cache_key]

    shortnames = _get_hero_shortnames()
    hero_id = STRATZ_HERO_TO_ID.get(hero_name)
    slug = shortnames.get(hero_id) if hero_id else None

    img = None
    if slug:
        url = HERO_ICON_CDN.format(slug=slug)
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                img = Image.open(io.BytesIO(r.content)).convert("RGBA")
                # Scale to a fixed height, keeping aspect ratio
                w, h = img.size
                new_h = size
                new_w = int(w * new_h / h)
                img = img.resize((new_w, new_h), Image.LANCZOS)
        except Exception:
            pass

    _hero_icon_cache[cache_key] = img
    return img


def _render_table_image(title, df, columns=None):
    """Render a DataFrame as a clean PNG table image. Returns bytes."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if columns:
        df = df[columns]

    n_rows, n_cols = df.shape
    col_widths = []
    for col in df.columns:
        max_len = max(len(str(col)), df[col].astype(str).str.len().max() if len(df) else 0)
        col_widths.append(max(max_len * 0.12, 0.6))
    fig_width = max(sum(col_widths) + 0.4, 4)
    fig_height = max((n_rows + 2) * 0.35 + 0.5, 1.5)

    fig, ax = plt.subplots(figsize=(fig_width, fig_height))
    ax.axis("off")
    ax.set_title(title, fontsize=13, fontweight="bold", pad=12, loc="left")

    cell_text = df.values.tolist()
    table = ax.table(
        cellText=cell_text,
        colLabels=df.columns.tolist(),
        cellLoc="center",
        loc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1, 1.4)

    # Style header
    for j in range(n_cols):
        cell = table[0, j]
        cell.set_facecolor("#2d2d2d")
        cell.set_text_props(color="white", fontweight="bold")

    # Alternate row colors
    for i in range(1, n_rows + 1):
        color = "#f9f9f9" if i % 2 == 0 else "#ffffff"
        for j in range(n_cols):
            table[i, j].set_facecolor(color)

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                facecolor="white", edgecolor="none")
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


def generate_player_image(data, steam_id):
    """Generate a PNG image of a player's hero pool with hero icons."""
    from PIL import Image, ImageDraw, ImageFont

    sid = normalize_steam_id(steam_id)
    name = data["player_names"].get(sid, str(sid))
    df = data.get("player_heroes", {}).get(sid, pd.DataFrame())
    if df.empty:
        return None

    # Limit to top 15 heroes
    df = df.head(15)

    # Layout constants
    ICON_SIZE = 48
    ROW_H = 56
    PAD = 18
    HEADER_H = 72
    COL_ICON_W = 96
    COL_HERO_W = 240
    COL_GAMES_W = 90
    COL_WINS_W = 90
    COL_WR_W = 105
    COL_LAST_W = 150
    COLS = [COL_ICON_W, COL_HERO_W, COL_GAMES_W, COL_WINS_W, COL_WR_W, COL_LAST_W]
    TABLE_W = sum(COLS)
    IMG_W = TABLE_W + 2 * PAD
    n_rows = len(df)
    IMG_H = HEADER_H + ROW_H + n_rows * ROW_H + PAD  # header + col header + rows

    img = Image.new("RGB", (IMG_W, IMG_H), "#1a1a2e")
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
        font_bold = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)
        font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 24)
    except OSError:
        font = ImageFont.load_default()
        font_bold = font
        font_title = font

    # Title
    draw.text((PAD, PAD), f"{name} — Hero Pool (2 months)", fill="#e0e0e0", font=font_title)

    # Column headers
    y = HEADER_H
    headers = ["", "Hero", "Games", "Wins", "WR%", "Last Played"]
    x = PAD
    draw.rectangle([PAD, y, PAD + TABLE_W, y + ROW_H], fill="#16213e")
    for i, hdr in enumerate(headers):
        draw.text((x + 6, y + 16), hdr, fill="#e0e0e0", font=font_bold)
        x += COLS[i]

    # Rows
    for row_idx in range(n_rows):
        row = df.iloc[row_idx]
        y = HEADER_H + ROW_H + row_idx * ROW_H
        bg = "#0f3460" if row_idx % 2 == 0 else "#1a1a2e"
        draw.rectangle([PAD, y, PAD + TABLE_W, y + ROW_H], fill=bg)

        x = PAD
        # Hero icon
        hero_icon = _get_hero_icon(row["Hero"], ICON_SIZE)
        if hero_icon:
            icon_y = y + (ROW_H - ICON_SIZE) // 2
            img.paste(hero_icon, (x + 6, icon_y), hero_icon)
        x += COLS[0]

        # Hero name
        draw.text((x + 6, y + 16), str(row["Hero"]), fill="#e0e0e0", font=font)
        x += COLS[1]

        # Games
        draw.text((x + 6, y + 16), str(int(row["Games"])), fill="#e0e0e0", font=font)
        x += COLS[2]

        # Wins
        draw.text((x + 6, y + 16), str(int(row["Wins"])), fill="#e0e0e0", font=font)
        x += COLS[3]

        # Winrate with color
        wr = row["Winrate"]
        wr_color = "#4ecca3" if wr >= 50 else "#e84545"
        draw.text((x + 6, y + 16), f"{wr:.1f}%", fill=wr_color, font=font_bold)
        x += COLS[4]

        # Last played
        draw.text((x + 6, y + 16), str(row["Last Played"]), fill="#b0b0b0", font=font)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()


def generate_team_games_image(data, team_name):
    """Generate a PNG image of the team games table with hero icons."""
    from PIL import Image, ImageDraw, ImageFont

    team_games = data.get("team_games", pd.DataFrame())
    if team_games.empty:
        return None

    # Prioritize 3+ player games and limit to 15
    team_games = team_games.head(15)

    # Layout constants
    ICON_SIZE = 36
    ROW_H = 48
    PAD = 18
    HEADER_H = 72
    COL_DATE_W = 180
    COL_TOUR_W = 60
    COL_NPLAY_W = 38
    COL_POS_W = 315  # each position column — icon + player name + hero name
    COL_RESULT_W = 75
    COLS = [COL_DATE_W, COL_TOUR_W, COL_NPLAY_W] + [COL_POS_W] * 5 + [COL_RESULT_W]
    TABLE_W = sum(COLS)
    IMG_W = TABLE_W + 2 * PAD
    n_rows = len(team_games)
    IMG_H = HEADER_H + ROW_H + n_rows * ROW_H + PAD

    img = Image.new("RGB", (IMG_W, IMG_H), "#1a1a2e")
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
        font_bold = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
        font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 21)
    except OSError:
        font = ImageFont.load_default()
        font_bold = font
        font_title = font

    # Title
    draw.text((PAD, PAD), f"{team_name} — Team Games (2 months)", fill="#e0e0e0", font=font_title)

    # Column headers
    y = HEADER_H
    headers = ["Date", "T", "#", "Pos 1", "Pos 2", "Pos 3", "Pos 4", "Pos 5", "Result"]
    x = PAD
    draw.rectangle([PAD, y, PAD + TABLE_W, y + ROW_H], fill="#16213e")
    for i, hdr in enumerate(headers):
        draw.text((x + 6, y + 12), hdr, fill="#e0e0e0", font=font_bold)
        x += COLS[i]

    pos_cols = ["Pos 1", "Pos 2", "Pos 3", "Pos 4", "Pos 5"]

    for row_idx in range(n_rows):
        row = team_games.iloc[row_idx]
        y = HEADER_H + ROW_H + row_idx * ROW_H
        bg = "#0f3460" if row_idx % 2 == 0 else "#1a1a2e"
        draw.rectangle([PAD, y, PAD + TABLE_W, y + ROW_H], fill=bg)

        x = PAD
        # Date
        draw.text((x + 6, y + 12), str(row["Date"]), fill="#e0e0e0", font=font)
        x += COLS[0]

        # Tournament
        tour_val = str(row.get("Tournament", ""))
        if tour_val and tour_val not in ("", "nan"):
            draw.text((x + 6, y + 12), "Yes", fill="#f0c040", font=font_bold)
        x += COLS[1]

        # # Players
        draw.text((x + 6, y + 12), str(int(row["# Players"])), fill="#e0e0e0", font=font)
        x += COLS[2]

        # Position columns — show icon + name
        for pc in pos_cols:
            val = str(row.get(pc, ""))
            if val and val != "nan":
                # Extract hero name from "Player (Hero)" format
                hero_name = None
                if "(" in val and val.endswith(")"):
                    hero_name = val[val.rfind("(") + 1:-1]

                hero_icon = _get_hero_icon(hero_name, ICON_SIZE) if hero_name else None
                if hero_icon:
                    icon_y = y + (ROW_H - ICON_SIZE) // 2
                    img.paste(hero_icon, (x + 3, icon_y), hero_icon)
                    # Show player name (without hero) after icon
                    player_part = val[:val.rfind("(")].strip()
                    draw.text((x + ICON_SIZE + 8, y + 12), player_part, fill="#e0e0e0", font=font)
                else:
                    draw.text((x + 6, y + 12), val, fill="#e0e0e0", font=font)
            x += COL_POS_W

        # Result
        result = str(row.get("Result", ""))
        r_color = "#4ecca3" if result == "Won" else "#e84545" if result == "Lost" else "#e0e0e0"
        draw.text((x + 6, y + 12), result, fill=r_color, font=font_bold)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()


def generate_drafts_image(data, team_name):
    """Generate a PNG image showing tournament drafts with colored hero icons."""
    from PIL import Image, ImageDraw, ImageFont

    drafts = data.get("drafts", [])
    if not drafts:
        return None

    # Limit to 15 most recent drafts
    drafts = drafts[:15]

    ICON_W = 82
    ICON_H = 46
    CELL_W = ICON_W + 12
    CELL_H = ICON_H + 12
    PAD = 18
    HEADER_H = 72
    MATCH_GAP = 10
    TEAM_COL_W = 210
    SIDE_COL_W = 100
    MAX_ACTIONS = max((max((a["order"] for a in d["actions"]), default=-1) + 1 for d in drafts), default=24)

    TABLE_W = TEAM_COL_W + SIDE_COL_W + MAX_ACTIONS * CELL_W
    IMG_W = TABLE_W + 2 * PAD

    # Each draft: match header (20px) + 2 team rows
    MATCH_HEADER_H = 34
    DRAFT_H = MATCH_HEADER_H + 2 * CELL_H
    IMG_H = HEADER_H + len(drafts) * (DRAFT_H + MATCH_GAP) + PAD

    img = Image.new("RGB", (IMG_W, IMG_H), "#1a1a2e")
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
        font_bold = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
        font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 21)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
    except OSError:
        font = ImageFont.load_default()
        font_bold = font
        font_title = font
        font_small = font

    draw.text((PAD, PAD), f"{team_name} — Tournament Drafts", fill="#e0e0e0", font=font_title)

    PICK_BG = (46, 125, 50)   # green
    BAN_BG = (198, 40, 40)    # red
    EMPTY_BG = (26, 26, 46)   # match background
    HIGHLIGHT_NAME_BG = (30, 60, 110)  # brighter bg for team of interest
    DEFAULT_NAME_BG = (22, 33, 62)     # #16213e

    y = HEADER_H
    for draft in drafts:
        # Match header
        winner_str = "\U0001f3c6 " + draft["winner"]
        label = f"{draft['radiant']} vs {draft['dire']} — {winner_str} — {draft['date']}"
        draw.text((PAD, y + 5), label, fill="#c0c0c0", font=font_small)
        y += MATCH_HEADER_H

        actions_by_order = {a["order"]: a for a in draft["actions"]}

        for team_name_row, side in [(draft["radiant"], "Radiant"), (draft["dire"], "Dire")]:
            is_our_team = team_name_row.strip().lower() == team_name.strip().lower()
            name_bg = HIGHLIGHT_NAME_BG if is_our_team else DEFAULT_NAME_BG
            name_color = "#f0c040" if is_our_team else "#e0e0e0"
            x = PAD
            # Team name
            draw.rectangle([x, y, x + TEAM_COL_W, y + CELL_H], fill=name_bg)
            draw.text((x + 6, y + 12), team_name_row[:22], fill=name_color, font=font_bold)
            x += TEAM_COL_W

            # Side
            draw.rectangle([x, y, x + SIDE_COL_W, y + CELL_H], fill=name_bg)
            draw.text((x + 6, y + 12), side, fill=name_color, font=font)
            x += SIDE_COL_W

            # Draft cells
            for i in range(MAX_ACTIONS):
                a = actions_by_order.get(i)
                if a and a["side"] == side:
                    bg = PICK_BG if a["type"] == "Pick" else BAN_BG
                    draw.rectangle([x, y, x + CELL_W, y + CELL_H], fill=bg)
                    hero_icon = _get_hero_icon(a["hero"], ICON_H)
                    if hero_icon:
                        ix = x + (CELL_W - hero_icon.width) // 2
                        iy = y + (CELL_H - ICON_H) // 2
                        img.paste(hero_icon, (ix, iy), hero_icon)
                else:
                    draw.rectangle([x, y, x + CELL_W, y + CELL_H], fill=EMPTY_BG)
                x += CELL_W

            y += CELL_H

        y += MATCH_GAP

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()


def generate_full_scouting_image(data, team_name, players):
    """Generate a single composite image: team games + drafts on top, all players side by side below."""
    from PIL import Image

    player_imgs = []
    for p in players:
        img_bytes = generate_player_image(data, p["steam_id"])
        if img_bytes:
            player_imgs.append(Image.open(io.BytesIO(img_bytes)))

    team_img = None
    team_bytes = generate_team_games_image(data, team_name)
    if team_bytes:
        team_img = Image.open(io.BytesIO(team_bytes))

    drafts_img = None
    drafts_bytes = generate_drafts_image(data, team_name)
    if drafts_bytes:
        drafts_img = Image.open(io.BytesIO(drafts_bytes))

    if not player_imgs and not team_img and not drafts_img:
        return None

    GAP = 10

    # Top row: team games and drafts side by side
    top_imgs = [im for im in [team_img, drafts_img] if im is not None]
    top_w = sum(im.width for im in top_imgs) + GAP * max(len(top_imgs) - 1, 0) if top_imgs else 0
    top_h = max((im.height for im in top_imgs), default=0)

    # Bottom row: all players side by side
    players_w = sum(im.width for im in player_imgs) + GAP * max(len(player_imgs) - 1, 0) if player_imgs else 0
    players_h = max((im.height for im in player_imgs), default=0)

    total_w = max(top_w, players_w)
    total_h = 0
    if top_imgs:
        total_h += top_h + GAP
    total_h += players_h

    composite = Image.new("RGB", (total_w, total_h), "#1a1a2e")

    y = 0
    # Top row: team games + drafts side by side
    x = 0
    for im in top_imgs:
        composite.paste(im, (x, y))
        x += im.width + GAP
    if top_imgs:
        y += top_h + GAP

    # Bottom row: all players side by side
    x = 0
    for im in player_imgs:
        composite.paste(im, (x, y))
        x += im.width + GAP

    buf = io.BytesIO()
    composite.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()
