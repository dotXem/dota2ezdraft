"""Pro Meta: fetch tournament data from Stratz and compute hero stats."""

import json
import time
import datetime
import requests
import pandas as pd
from get_data_from_stratz import (
    STRATZ_API_URL, HEADERS, STRATZ_ID_TO_HERO, STRATZ_HERO_TO_ID
)
from scouting_api import get_hero_icon_url


# ---------------------------------------------------------------------------
# League listing
# ---------------------------------------------------------------------------


def _gql(query):
    """Execute a GraphQL query with rate limiting."""
    time.sleep(1)
    payload = json.dumps({"query": query})
    r = requests.post(STRATZ_API_URL, headers=HEADERS, data=payload, timeout=30)
    r.raise_for_status()
    data = r.json()
    if "errors" in data:
        raise RuntimeError(data["errors"])
    return data


def fetch_recent_leagues(count=20):
    """Return list of recent pro/premium leagues from OpenDota, sorted by last match."""
    sql = (
        "SELECT l.leagueid, l.name, l.tier, "
        "COUNT(m.match_id) AS match_count, "
        "MAX(m.start_time) AS last_match "
        "FROM leagues l JOIN matches m ON l.leagueid = m.leagueid "
        "WHERE l.tier IN ('professional', 'premium') "
        "AND m.start_time > extract(epoch from now() - interval '6 months') "
        "GROUP BY l.leagueid, l.name, l.tier "
        "HAVING COUNT(m.match_id) >= 10 "
        "ORDER BY last_match DESC "
        f"LIMIT {int(count)}"
    )
    rows = _opendota_sql(sql)
    results = []
    for r in rows:
        last_ts = r.get("last_match") or 0
        last_dt = datetime.datetime.fromtimestamp(last_ts, tz=datetime.timezone.utc)
        results.append({
            "id": r["leagueid"],
            "name": r["name"],
            "tier": r["tier"],
            "match_count": r["match_count"],
            "last_match": last_dt.strftime("%Y-%m-%d"),
        })
    return results


# ---------------------------------------------------------------------------
# Fetch all matches for a league (paginated)
# ---------------------------------------------------------------------------

_MATCH_FIELDS = """
    id
    startDateTime
    didRadiantWin
    radiantTeam { name }
    direTeam { name }
    pickBans {
        isPick
        heroId
        order
        bannedHeroId
        isRadiant
    }
    players {
        steamAccountId
        heroId
        isRadiant
        position
    }
"""


OPENDOTA_API_URL = "https://api.opendota.com/api"


def lookup_league_info(league_id):
    """Look up league name and tier from OpenDota (works for new leagues)."""
    r = requests.get(f"{OPENDOTA_API_URL}/leagues/{league_id}", timeout=15)
    if r.status_code == 200:
        data = r.json()
        return {
            "id": league_id,
            "name": data.get("name") or f"League {league_id}",
            "tier": data.get("tier") or "unknown",
        }
    return {"id": league_id, "name": f"League {league_id}", "tier": "unknown"}


def _opendota_sql(sql):
    """Run a SQL query against the OpenDota Explorer API."""
    r = requests.get(f"{OPENDOTA_API_URL}/explorer", params={"sql": sql}, timeout=60)
    r.raise_for_status()
    data = r.json()
    if data.get("err"):
        raise RuntimeError(data["err"])
    return data.get("rows", [])


def _fetch_via_stratz(league_id):
    """Fetch matches via Stratz league query (fast, paginated)."""
    all_matches = []
    skip = 0
    while True:
        q = """
        {
          league(id: %d) {
            matches(request: {take: 100, skip: %d}) {
              %s
            }
          }
        }
        """ % (league_id, skip, _MATCH_FIELDS)
        data = _gql(q)
        league_data = data["data"]["league"]
        if league_data is None:
            return None  # League not indexed in Stratz
        matches = league_data["matches"]
        if not matches:
            break
        all_matches.extend(matches)
        if len(matches) < 100:
            break
        skip += 100
    return all_matches


def _fetch_via_opendota(league_id):
    """Fetch all match data for a league using OpenDota SQL Explorer.

    Uses 3 bulk SQL queries instead of N individual match requests:
      1. picks/bans for all matches
      2. players + match metadata for all matches
      3. team names
    Returns matches in the same format as Stratz for compatibility.
    """
    # 1) Picks/bans
    pb_rows = _opendota_sql(
        "SELECT match_id, hero_id, is_pick, team, ord "
        "FROM picks_bans WHERE match_id IN "
        f"(SELECT match_id FROM matches WHERE leagueid = {int(league_id)})"
    )
    time.sleep(1)

    # 2) Players + match metadata
    pm_rows = _opendota_sql(
        "SELECT m.match_id, m.start_time, m.radiant_win, "
        "m.radiant_team_id, m.dire_team_id, "
        "pm.hero_id, pm.player_slot "
        "FROM matches m "
        "JOIN player_matches pm ON m.match_id = pm.match_id "
        f"WHERE m.leagueid = {int(league_id)}"
    )
    time.sleep(1)

    if not pm_rows:
        return []

    # 3) Resolve team names
    team_ids = set()
    for row in pm_rows:
        if row.get("radiant_team_id"):
            team_ids.add(row["radiant_team_id"])
        if row.get("dire_team_id"):
            team_ids.add(row["dire_team_id"])

    team_names = {}
    if team_ids:
        ids_str = ",".join(str(tid) for tid in team_ids)
        team_rows = _opendota_sql(
            f"SELECT team_id, name FROM teams WHERE team_id IN ({ids_str})"
        )
        team_names = {r["team_id"]: r["name"] for r in team_rows}

    # Group picks/bans by match
    pb_by_match = {}
    for row in pb_rows:
        mid = row["match_id"]
        pb_by_match.setdefault(mid, []).append({
            "isPick": row["is_pick"],
            "heroId": row["hero_id"],
            "order": row["ord"],
            "bannedHeroId": row["hero_id"] if not row["is_pick"] else None,
            "isRadiant": row["team"] == 0,
        })

    # Group players and match info by match
    match_info = {}   # match_id -> {start_time, radiant_win, rad_team, dire_team}
    players_by_match = {}
    for row in pm_rows:
        mid = row["match_id"]
        if mid not in match_info:
            rad_tid = row.get("radiant_team_id")
            dire_tid = row.get("dire_team_id")
            match_info[mid] = {
                "start_time": row["start_time"],
                "radiant_win": row["radiant_win"],
                "rad_team": team_names.get(rad_tid, "Radiant"),
                "dire_team": team_names.get(dire_tid, "Dire"),
            }
        slot = row["player_slot"]
        is_radiant = slot < 128
        players_by_match.setdefault(mid, []).append({
            "heroId": row["hero_id"],
            "isRadiant": is_radiant,
            "position": None,  # Not available from OpenDota
            "steamAccountId": None,
        })

    # Build match objects in Stratz-compatible format
    matches = []
    for mid, info in match_info.items():
        matches.append({
            "id": mid,
            "startDateTime": info["start_time"],
            "didRadiantWin": info["radiant_win"],
            "radiantTeam": {"name": info["rad_team"]},
            "direTeam": {"name": info["dire_team"]},
            "pickBans": sorted(pb_by_match.get(mid, []), key=lambda x: x["order"]),
            "players": players_by_match.get(mid, []),
        })
    return matches


def fetch_league_matches(league_id, progress_cb=None):
    """Fetch all matches from a league.

    Tries Stratz league query first (fast). If the league isn't indexed
    in Stratz yet, falls back to OpenDota SQL Explorer (3 bulk queries).

    progress_cb is accepted for API compatibility but the OpenDota path
    is fast enough not to need it.
    """
    # Fast path: Stratz has the league
    result = _fetch_via_stratz(league_id)
    if result is not None:
        return result

    # Fallback: 100% OpenDota via SQL Explorer
    return _fetch_via_opendota(league_id)


# ---------------------------------------------------------------------------
# Compute hero contest stats from matches
# ---------------------------------------------------------------------------

def compute_hero_stats(matches):
    """
    Compute per-hero pick/ban/win stats.
    Returns a DataFrame with: Icon, Hero, Picks, Bans, Contested, Pick%, Ban%,
    Contest%, Winrate, and per-position pick counts.
    """
    total_matches = len(matches)
    hero_data = {}  # heroId -> {picks, bans, wins, pos counts}

    for m in matches:
        picked_heroes = set()
        # Pick/ban phase
        for pb in (m.get("pickBans") or []):
            hid = pb.get("heroId")
            if hid is None:
                continue
            entry = hero_data.setdefault(hid, {
                "picks": 0, "bans": 0, "wins": 0,
                "pos1": 0, "pos2": 0, "pos3": 0, "pos4": 0, "pos5": 0,
            })
            if pb["isPick"]:
                entry["picks"] += 1
                picked_heroes.add((hid, pb["isRadiant"]))
            else:
                entry["bans"] += 1

        # Win tracking and position from players
        radiant_win = m.get("didRadiantWin")
        for p in (m.get("players") or []):
            hid = p["heroId"]
            is_radiant = p["isRadiant"]
            pos = p.get("position") or ""
            pos_map = {
                "POSITION_1": "pos1", "POSITION_2": "pos2", "POSITION_3": "pos3",
                "POSITION_4": "pos4", "POSITION_5": "pos5",
            }
            pos_key = pos_map.get(pos)

            if hid in hero_data and (hid, is_radiant) in picked_heroes:
                if radiant_win is not None:
                    won = (is_radiant == radiant_win)
                    if won:
                        hero_data[hid]["wins"] += 1
                if pos_key:
                    hero_data[hid][pos_key] += 1

    rows = []
    for hid, s in hero_data.items():
        hero_name = STRATZ_ID_TO_HERO.get(hid, f"Unknown ({hid})")
        picks = s["picks"]
        bans = s["bans"]
        contested = picks + bans
        wr = round(s["wins"] / picks * 100, 1) if picks else 0.0
        pick_pct = round(picks / total_matches * 100, 1) if total_matches else 0.0
        ban_pct = round(bans / total_matches * 100, 1) if total_matches else 0.0
        contest_pct = round(contested / total_matches * 100, 1) if total_matches else 0.0

        rows.append({
            "Icon": get_hero_icon_url(hero_name) or "",
            "Hero": hero_name,
            "Picks": picks,
            "Bans": bans,
            "Contested": contested,
            "Pick%": pick_pct,
            "Ban%": ban_pct,
            "Contest%": contest_pct,
            "Winrate": wr,
            "Pos 1": s["pos1"],
            "Pos 2": s["pos2"],
            "Pos 3": s["pos3"],
            "Pos 4": s["pos4"],
            "Pos 5": s["pos5"],
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("Contested", ascending=False).reset_index(drop=True)
    return df, total_matches


# ---------------------------------------------------------------------------
# Build draft order table for recent matches
# ---------------------------------------------------------------------------

def build_draft_table(matches, num_matches=20):
    """
    Build a table showing the draft order for the most recent matches.
    Returns a list of dicts, each representing one match's draft.
    """
    # Sort by startDateTime descending
    sorted_matches = sorted(matches, key=lambda m: m.get("startDateTime", 0), reverse=True)

    drafts = []
    for m in sorted_matches[:num_matches]:
        ts = m.get("startDateTime", 0)
        dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
        rad_team = (m.get("radiantTeam") or {}).get("name", "Radiant")
        dire_team = (m.get("direTeam") or {}).get("name", "Dire")
        rad_win = m.get("didRadiantWin")
        winner = rad_team if rad_win else dire_team

        pick_bans = sorted(m.get("pickBans") or [], key=lambda x: x.get("order", 0))

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
            "match_id": m["id"],
            "date": dt.strftime("%Y-%m-%d %H:%M"),
            "radiant": rad_team,
            "dire": dire_team,
            "winner": winner,
            "actions": actions,
        })

    return drafts


def draft_to_html(draft):
    """Convert a single draft dict to an HTML table with colored hero icons.

    Each team gets one row. Columns correspond to draft order positions (0-23).
    A team's cell is filled only when that team acted; otherwise it's empty.
    """
    # Index actions by order
    actions_by_order = {a["order"]: a for a in draft["actions"]}
    max_order = max(actions_by_order.keys(), default=-1) + 1

    def _hero_cell(action):
        bg = "#2e7d32" if action["type"] == "Pick" else "#c62828"
        return (
            f'<td style="background:{bg};padding:6px 4px;text-align:center;">'
            f'<img src="{action["icon"]}" title="{action["hero"]} ({action["type"]})" '
            f'style="display:block;margin:0 auto;width:42px;height:24px;min-width:42px;min-height:24px;max-width:42px;max-height:24px;border-radius:2px;">'
            f'</td>'
        )

    _empty = '<td style="padding:6px 4px;min-width:50px;"></td>'

    def _team_cells(side):
        cells = ""
        for i in range(max_order):
            a = actions_by_order.get(i)
            if a and a["side"] == side:
                cells += _hero_cell(a)
            else:
                cells += _empty
        return cells

    # Header: order numbers
    hdr_cells = "".join(
        f'<th style="padding:2px 1px;text-align:center;color:#888;font-size:10px;">{i+1}</th>'
        for i in range(max_order)
    )

    html = (
        '<table style="border-collapse:collapse;font-size:13px;">'
        '<tr style="background:#1a1a2e;color:#eee;">'
        '<th style="padding:4px 8px;text-align:left;min-width:120px;">Team</th>'
        '<th style="padding:4px 8px;text-align:left;min-width:70px;">Side</th>'
        + hdr_cells +
        '</tr>'
    )

    for team_name, side in [
        (draft["radiant"], "Radiant"),
        (draft["dire"], "Dire"),
    ]:
        html += (
            f'<tr>'
            f'<td style="padding:4px 8px;font-weight:bold;vertical-align:middle;">{team_name}</td>'
            f'<td style="padding:4px 8px;vertical-align:middle;">{side}</td>'
            f'{_team_cells(side)}'
            f'</tr>'
        )

    html += '</table>'
    return html


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def fetch_pro_meta(league_id, progress_cb=None):
    """Fetch and compute all pro meta data for a league."""
    matches = fetch_league_matches(league_id, progress_cb=progress_cb)
    hero_stats, total_matches = compute_hero_stats(matches)
    drafts = build_draft_table(matches, num_matches=20)

    return {
        "league_id": league_id,
        "total_matches": total_matches,
        "hero_stats": hero_stats,
        "drafts": drafts,
        "matches_raw": matches,
        "fetched_at": datetime.datetime.utcnow().isoformat(),
    }
