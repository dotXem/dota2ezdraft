# AGENTS.md

Orientation for agents and contributors working on **EZDraft**. It's a Streamlit app for Dota 2 drafting: it suggests heroes from counter and synergy scores, shows pro tournament meta, and builds scouting reports on opponent teams. It runs on GCP Cloud Run, and its data lives in the GCS bucket `heroes-ezdraft`.

For user-facing setup see [README.md](README.md). For Cloud Run, see [DEPLOY.md](DEPLOY.md), but read the deploy caveats below first.

---

## Quick start

```bash
# .env: STRATZ_API_TOKEN=...  and, for development, EZDRAFT_USERS_PATH=users.local.yaml
gcloud auth application-default login   # only needed for the production accounts
pip install -r requirements.txt
streamlit run streamlit_app.py          # http://localhost:8501
```

- **Every module fails at import without `STRATZ_API_TOKEN`.** `get_data_from_stratz.py` reads `os.environ["STRATZ_API_TOKEN"]` at module level, and every other module imports from it. `python-dotenv` loads it from `.env`.
- **Use a local users file for development.** By default the app reads and writes the **production** accounts in `gs://ezdraft-private/users.yaml`. With `EZDRAFT_USERS_PATH=users.local.yaml` (gitignored), accounts and lists stay in a local file that's created on first run. Data snapshots come from the public `heroes-ezdraft` bucket, which works without credentials (gcsfs falls back to anonymous access).
- GCS credentials come from `.streamlit/secrets.toml` (`[connections.gcs]`) if present, otherwise from Application Default Credentials. Production has no `secrets.toml` and uses the Cloud Run service account.
- Prod uses Python 3.11 (Docker). Any 3.11+ works locally.

### Tests (`pip install -r requirements-dev.txt`)

| Command | What it runs | Time |
|---|---|---|
| `pytest` | Offline: scoring (`test_scoring.py`), daily snapshot assembly and upload with Stratz/GCS stubbed (`test_daily_fetch.py`), hero grid files (`test_hero_grid.py`), OpenDota limiter and match merge (`test_opendota.py`) | ~10 s |
| `pytest -m e2e` | The whole app in-process via Streamlit's `AppTest`: draft, accounts, hero lists, Pro Meta, Scouting, Config. Needs network and `STRATZ_API_TOKEN` | ~2 min |
| `pytest -m cloud` | Read-only smoke test of the deployed service over its websocket, including data freshness (≤ 2 days). `EZDRAFT_URL` overrides the URL | ~30 s |

- `tests/conftest.py` points `EZDRAFT_USERS_PATH` at a throwaway file, and the e2e tests send GCS writes to an in-memory filesystem, so tests never touch production data.
- The scouting e2e test picks five players from a recent pro match. Don't hardcode personal Steam IDs: the repo is public.
- `AppTest` quirks the e2e tests work around:
  - A click reruns the whole app, so `st.rerun(scope="fragment")` raises there, though it works in a browser.
  - The streamlit-authenticator cookie component doesn't run, so logout needs an extra `run()`.
  - Deleting a keyed widget breaks later reruns of the same session.
- `python hero_suggestion.py` does **not** work: its `__main__` block calls `suggest_heroes_from_ally_and_enemy` with outdated arguments.

---

## File map

| File | Role |
|---|---|
| `streamlit_app.py` | **The app.** Login/registration sidebar, data-file and bracket selectors, and 5 tabs: Draft, My Hero Lists, Pro Meta, Scouting, Config (the last two only for whitelisted users). All UI lives here. |
| `hero_suggestion.py` | Pure pandas/numpy scoring logic for the Draft tab (no I/O). See *Scoring model*. |
| `get_data_from_stratz.py` | Stratz GraphQL client and shared constants: `STRATZ_API_URL`, `HEADERS`, `HEROES`, `BRACKETS`, `STRATZ_HERO_TO_ID`/`STRATZ_ID_TO_HERO`. Builds the daily matchup snapshot. Run directly, it writes `./<date>.yaml`. |
| `fetch_and_upload.py` | Daily Cloud Run Job entrypoint. Calls `get_data_from_stratz()` and uploads to `gs://heroes-ezdraft/data/<YYYY-MM-DD>.yaml`. Stratz sometimes returns no matchups for 1–2 heroes for a whole day, which used to fail about 10% of runs. Their matchups are now copied from the latest snapshot (at most `MAX_FALLBACK_HEROES` = 5). Beyond that, or for a hero absent from that snapshot, the job fails and uploads nothing, because a partial snapshot breaks the app. |
| `user_manager.py` | Accounts, hero lists and scouting teams. Everything is in one YAML at `USERS_PATH`: the private `gs://ezdraft-private/users.yaml` by default, or a local file via `EZDRAFT_USERS_PATH`. Also exports `_get_fs()` and `BUCKET` (the public bucket), which the app reuses for image uploads. |
| `scouting_api.py` | Scouting tab backend: per-player Stratz match history (60 days, paginated) merged with OpenDota's (`merge_opendota_matches`: deduplicated by match ID, fills Stratz anonymous players, adds OpenDota-only matches without pick/bans or league), hero pools, team stacks, 5-stack tournament drafts, and PIL-rendered PNG reports. Also owns **`get_hero_icon_url()`**, which every tab uses. |
| `opendota_api.py` | Shared OpenDota client (`opendota_get`). Every OpenDota call goes through its process-wide limiter: 60 calls/min and 3000/day (free tier), also synced from OpenDota's `X-Rate-Limit-Remaining-*` headers. Past the daily limit it raises `OpenDotaDailyLimitError`, and Scouting then runs on Stratz alone. |
| `pro_meta_api.py` | Pro Meta tab backend. Lists leagues through OpenDota SQL Explorer and fetches league matches from Stratz, falling back to OpenDota. Computes pick/ban/contest stats. `draft_to_html()` renders drafts for both Pro Meta and Scouting. |
| `hero_grid.py` | Config tab backend. Reads and checks a Dota 2 `hero_grid_config.json` uploaded by the user (`load_hero_grid_config()`) and renders one of its grids as HTML (`hero_grid_to_html()`). `scouting_grid_config()` builds a grid from a scouted team: a row per player every 120, starting with an empty 20-high category named after the player, then one 80×80 single-hero category named `<games> <winrate>%` for each of the player's 12 most played heroes. It keeps the first 5 players only, so that no category goes lower than 600 (`SCOUT_MAX_HEIGHT`). The app never stores the file: added grids live in `st.session_state` (`config_added_<file id>`, and `config_replaced_<file id>` for the names of the file's grids they replaced: adding a team that already has a grid asks to replace it) and the user downloads the updated file (`dump_hero_grid_config()`). |
| `heroes.yaml` | Hero → `nicknames` (used for draft input aliases) and `roles` (`p1`–`p5`, **currently unused**). |
| `stratz_hero_to_id.yaml` | Hero display name → Stratz hero ID. **This defines the canonical hero list (`HEROES`).** |
| `hero_shortnames.yaml` | Stratz hero ID → icon slug (`gs://heroes-ezdraft/icons/<slug>.png`). Kept locally so icons don't depend on a Stratz call. Stratz once failed from Cloud Run; it works there as of 2026-10. |
| `Dockerfile` / `Dockerfile.job` / `cloudbuild-job.yaml` / `docker-compose.yml` | App image, daily job image, Cloud Build config for the job image, and the local compose setup. |
| `.streamlit/config.toml` | Server config (headless, port 8501, XSRF on). An optional, gitignored `.streamlit/secrets.toml` can hold a `[connections.gcs]` service-account key. |

### Legacy or unused code (not imported by the app; don't extend it)

- `user_heroes.yaml`: old hero lists, superseded by `heroes_lists` in `users.yaml`.
- `2024-09-*.yaml`: old-schema snapshots. They work with `hero_suggestion.py` but **not** with the app (no `winrate_brackets` or `positions`).
- In `scouting_api.py`, `generate_*_markdown()` and `_render_table_image()` are unused. In `pro_meta_api.py`, the `progress_cb` params are unused.
---

## External services and data

```
Cloud Scheduler (08:00 Europe/Paris) → Cloud Run Job (fetch_and_upload.py)
    → Stratz GraphQL → gs://heroes-ezdraft/data/YYYY-MM-DD.yaml
Streamlit app (Cloud Run "ezdraft", europe-west1, GCP project "ezdraft")
    ├─ reads  gs://heroes-ezdraft/data/*.yaml        (st.connection FilesConnection, ttl 600s)
    ├─ r/w    gs://ezdraft-private/users.yaml         (private bucket, gcsfs, user_manager)
    ├─ writes gs://heroes-ezdraft/scouting_images/    (shareable scouting PNGs)
    ├─ links  storage.googleapis.com/heroes-ezdraft/icons/<slug>.png  (public hero icons)
    ├─ Stratz GraphQL  (scouting, pro-meta league matches)  — Bearer token, 1 req/s self-throttle
    └─ OpenDota        (league list/info via /explorer SQL, match fallback, scouting match history) — no auth, 60/min and 3000/day
```

**Rate limits.** The Stratz helpers `time.sleep(1)` before each request. The daily fetch also caps itself at 100 requests per minute (`MAX_CALLS_PER_MINUTE`). That job makes about 127 matchup calls plus 5 others, so it takes several minutes, and its task timeout is 600 s. Keep the throttling when you add Stratz calls.

### Snapshot schema (`data/YYYY-MM-DD.yaml`, produced by `get_data_from_stratz()`)

```yaml
<Hero Name>:
  winrate: 0.51                    # overall, from heroVsHeroMatchup
  matchup_winrate: {<Hero>: 0.49}  # this hero's winrate vs <Hero>
  synergy_winrate: {<Hero>: 0.52}  # this hero's winrate with <Hero>
  winrate_brackets: {"[DIVINE,IMMORTAL]": 0.50, "[ANCIENT,LEGEND]": ..., ...}
  positions: [POSITION_1, POSITION_3]   # positions with ≥10% of the hero's games
```

- The bracket keys are built with `"[" + ",".join(bracket) + "]"` in both `get_data_from_stratz.py` and `streamlit_app.py`. Change both together.
- `get_data()` reads `stratz_data["Lion"]` to discover the brackets.
- Matchup data uses the week starting the Thursday before last, so the week is complete.

### Users store (`gs://ezdraft-private/users.yaml`)

```yaml
credentials: {usernames: {<user>: {name, password (bcrypt), email}}}   # streamlit-authenticator format
cookie: {name, key, expiry_days}
heroes_lists:   {<user>: {<list name>: [<Hero>, ...]}}
scouting_users: [<user>, ...]                     # grants the Scouting and Config tabs; edit by hand in GCS
scouting_teams: {<user>: {<team>: {players: [{steam_id: int (32-bit), name: str}]}}}
```

The config is loaded **once per browser session** into `st.session_state.user_config`, and every write saves the **whole file**. Two sessions writing at once means the last write wins and silently drops the other's changes. Account for this before adding more per-user state.

---

## Scoring model (Draft tab, `hero_suggestion.py`)

1. **Symmetrize** the pairwise data. Matchups: `(M + (1 − Mᵀ)) / 2`. Synergy: `(S + Sᵀ) / 2`.
2. **Counter score** of A against B: `w(A vs B) − (0.5 + (w_A − 0.5) − (w_B − 0.5))`. **Synergy score** of A with B: `w(A with B) − (0.5 + (w_A − 0.5) + (w_B − 0.5))`. Both measure performance above what the two heroes' solo winrates predict.
3. A candidate's **score** is the sum of its counter scores against the enemy picks plus the sum of its synergy scores with the ally picks.
4. **Exceptional interactions** are pairs in the top or bottom 10% of all pair scores (`±1`). **impact** is the candidate's sum over the picked heroes.
5. **relevance** (0–3) = `[bracket winrate ≥ 0.5] + [score ≥ 0] + [impact ≥ 0]`. The table sorts by relevance, then score, and rows are colored by relevance.

The bracket selector changes only the `winrate` column and the meta check. The counter and synergy scores always come from the overall `winrate`.

The identifiers spell it `exceptionnal_*` (double n). Keep that spelling consistent rather than fixing it in one place.

---

## Conventions and gotchas

- **Hero names are the join key everywhere.** They are display names such as `"Nature's Prophet"` or `"Anti-Mage"`. The exact string must match across `stratz_hero_to_id.yaml`, `heroes.yaml`, the snapshot data, and users' saved lists.
- **Pandas Copy-on-Write.** `requirements.txt` allows pandas 3, which enforces CoW, and the Docker build installs the newest allowed version. Writing through `df.values` (for example `np.fill_diagonal(df.values, …)`) raises `ValueError: underlying array is read-only` there. Use `.at` or `.loc`. Commit `1345ba8` fixed exactly this. Your local pandas may be 2.x and hide the bug, so `test_scoring.py` turns CoW on to catch it.
- **`streamlit-authenticator` is pinned at 0.3.3** because the app uses that version's API (`authenticator.login('sidebar')` returns a tuple). Newer versions break it. `bcrypt` comes in through this package.
- **Streamlit structure.** The Pro Meta and Scouting tabs are wrapped in `@st.fragment`, so their buttons rerun only the fragment. Use `st.rerun(scope="fragment")` inside them.
  - Fetched results are cached per session in `st.session_state` under `pro_meta_data_<league_id>` and `scout_data_<team>`, each with an ISO `fetched_at`. They are not shared between users.
  - Snapshot processing uses `@st.cache_data`, keyed on the file path.
  - Widget keys are prefixed by tab (`meta_*`, `scout_*`, `config_*`) to avoid collisions. Follow that pattern.
- **Hero grid files** (`hero_grid_config.json`, from `Steam/userdata/<id>/570/remote/cfg/`): `{version, configs: [{config_name, categories: [{category_name, x_position, y_position, width, height, hero_ids}]}]}`. `hero_ids` are Dota hero IDs, the same as Stratz's (`STRATZ_ID_TO_HERO`). `load_hero_grid_config()` returns the file untouched so it can be written back.
- **Draft dict format** is shared between `pro_meta_api.build_draft_table` and `scouting_api.build_scouting_drafts`: `{match_id, date, radiant, dire, winner, actions: [{order, type: "Pick"|"Ban", hero, icon, side: "Radiant"|"Dire", team}]}`. `draft_to_html()` and `generate_drafts_image()` both consume it.
- **OpenDota fallback matches** have `position: None`, and `steamAccountId` only for players with a public profile. The UI hides the `Pos *` columns when they're all zero.
- **Steam IDs** are normalized to 32-bit account IDs (`normalize_steam_id`), and both 32-bit and 64-bit input is accepted.
- **Image rendering** loads DejaVu fonts from `/usr/share/fonts/truetype/dejavu/`. If those are missing it falls back to PIL's small default font, and `python:3.11-slim` may not ship them.
- Commit messages in this repo are short and lowercase (`fix`, `add draft analysis`).

---

## Common tasks

### Add a new hero (patch day)

1. `stratz_hero_to_id.yaml`: add `'<Name>': <stratz id>`. This makes it part of `HEROES`. Until it's added, the daily job skips the hero, because it filters to known IDs.
2. `heroes.yaml`: add nicknames (lowercase aliases users type) and roles.
3. `hero_shortnames.yaml`: add `<id>: <slug>`, and upload the icon to `gs://heroes-ezdraft/icons/<slug>.png`.
4. Check that all three files list the same heroes (127 as of 2026-04).

### Grant Scouting access

This also grants the Config tab. Add the username to `scouting_users` in `gs://ezdraft-private/users.yaml` (or in your local users file). There is no admin UI for this.

### Deploy

The app (from DEPLOY.md):

```bash
gcloud builds submit --tag europe-west1-docker.pkg.dev/ezdraft/ezdraft/streamlit-app
gcloud run deploy ezdraft --image europe-west1-docker.pkg.dev/ezdraft/ezdraft/streamlit-app --region europe-west1
```

The daily job image is built from `Dockerfile.job` through `cloudbuild-job.yaml`, because `gcloud builds submit` has no flag for choosing a Dockerfile:

```bash
gcloud builds submit --config cloudbuild-job.yaml
gcloud run jobs update ezdraft-fetch --image europe-west1-docker.pkg.dev/ezdraft/ezdraft/fetch-job --region europe-west1
```

On Cloud Run, the token comes from Secret Manager (`stratz-api-token`) and GCS auth comes from the default compute service account.

The service should run with `--timeout=3600 --session-affinity`. Cloud Run closes websockets at the request timeout (300 s by default), and without affinity a reconnecting browser can land on another instance and lose its Streamlit session.

Which image to rebuild:
- The app image contains everything.
- The job image runs only `fetch_and_upload.py`, `get_data_from_stratz.py` and `stratz_hero_to_id.yaml`. A change to any of those (a new hero, for example) needs a job rebuild too.

Run `pytest` before deploying and `pytest -m cloud` after.

Deploying is outward-facing, so confirm with the maintainer before running these.

---

## Security notes

- Never commit secrets. `.env`, `.streamlit/secrets.toml`, `.secrets/` and the users files are in both `.gitignore` and `.dockerignore`. `gcloud builds submit` also respects `.gitignore`.
- **`gs://heroes-ezdraft` is publicly readable**, because hero icons and shared scouting images are served from it by public URL. Never store anything private there. Accounts belong in the private `ezdraft-private` bucket.
- The repo is public, and older commits contain expired Stratz tokens and a copy of `users.yaml`. Treat anything ever committed as public.
