# AGENTS.md

Orientation for agents and contributors working on **EZDraft**. It's a Streamlit app for Dota 2 drafting: it suggests heroes from counter and synergy scores, shows pro tournament meta, and builds scouting reports on opponent teams. It runs on GCP Cloud Run, and its data lives in the GCS bucket `heroes-ezdraft`.

For user-facing setup see [README.md](README.md). For Cloud Run, see [DEPLOY.md](DEPLOY.md), but read the deploy caveats below first.

---

## Quick start

```bash
# Needs: STRATZ_API_TOKEN (in .env or env) + GCS creds in .streamlit/secrets.toml
gcloud secrets versions access latest --secret=streamlit-local-secrets > .streamlit/secrets.toml
pip install -r requirements.txt
streamlit run streamlit_app.py          # http://localhost:8501
```

- **Every module fails at import without `STRATZ_API_TOKEN`.** `get_data_from_stratz.py` reads `os.environ["STRATZ_API_TOKEN"]` at module level, and every other module imports from it. `python-dotenv` loads it from `.env`.
- **Local runs use the production bucket.** There is no dev bucket or dev users store. With the shared credentials, signing up, editing hero lists or saving scouting teams locally writes to the live `gs://heroes-ezdraft/users.yaml`. Without credentials, gcsfs falls back to anonymous access: the data snapshots can be read, but every write fails with an `HttpError`.
- Prod uses Python 3.11 (Docker). Any 3.11+ works locally.

### Verifying changes (there are no tests, linters or CI)

The scoring pipeline runs offline against a bundled snapshot in about 6 s:

```bash
python3 - <<'EOF'
import yaml
from hero_suggestion import *
data = yaml.safe_load(open('2024-09-21.yaml'))
w, e, a = create_winrate_enemy_synergy_dfs(data)
c, s = compute_counter_scores(w, e), compute_synergy_scores(w, a)
ec, es = identify_exceptional_interactions(c), identify_exceptional_interactions(s)
df = suggest_heroes_from_ally_and_enemy(w, c, s, ec, es, ["Faceless Void", "Techies"], ["Lich"])
print(df.sort_values(["relevance", "score"], ascending=False).head())
EOF
```

To check UI changes, run `streamlit run streamlit_app.py` and use the affected tab. `python hero_suggestion.py` does **not** work: its `__main__` block calls `suggest_heroes_from_ally_and_enemy` with outdated arguments.

---

## File map

| File | Role |
|---|---|
| `streamlit_app.py` | **The app.** Login/registration sidebar, data-file and bracket selectors, and 4 tabs: Draft, My Hero Lists, Pro Meta, Scouting (Scouting only for whitelisted users). All UI lives here. |
| `hero_suggestion.py` | Pure pandas/numpy scoring logic for the Draft tab (no I/O). See *Scoring model*. |
| `get_data_from_stratz.py` | Stratz GraphQL client and shared constants: `STRATZ_API_URL`, `HEADERS`, `HEROES`, `BRACKETS`, `STRATZ_HERO_TO_ID`/`STRATZ_ID_TO_HERO`. Builds the daily matchup snapshot. Run directly, it writes `./<date>.yaml`. |
| `fetch_and_upload.py` | Daily Cloud Run Job entrypoint. Calls `get_data_from_stratz()` and uploads to `gs://heroes-ezdraft/data/<YYYY-MM-DD>.yaml`. Fails if fewer than `len(HEROES)` heroes were fetched. |
| `user_manager.py` | Accounts, hero lists and scouting teams. Everything is in one YAML on GCS (`heroes-ezdraft/users.yaml`). Also exports `_get_fs()` and `BUCKET`, which the app reuses for image uploads. |
| `scouting_api.py` | Scouting tab backend: per-player Stratz match history (60 days, paginated), hero pools, team stacks, 5-stack tournament drafts, and PIL-rendered PNG reports. Also owns **`get_hero_icon_url()`**, which every tab uses. |
| `pro_meta_api.py` | Pro Meta tab backend. Lists leagues through OpenDota SQL Explorer and fetches league matches from Stratz, falling back to OpenDota. Computes pick/ban/contest stats. `draft_to_html()` renders drafts for both Pro Meta and Scouting. |
| `heroes.yaml` | Hero → `nicknames` (used for draft input aliases) and `roles` (`p1`–`p5`, **currently unused**). |
| `stratz_hero_to_id.yaml` | Hero display name → Stratz hero ID. **This defines the canonical hero list (`HEROES`).** |
| `hero_shortnames.yaml` | Stratz hero ID → icon slug (`gs://heroes-ezdraft/icons/<slug>.png`). Kept locally because Stratz calls were failing from Cloud Run (see the comment in `_get_hero_shortnames`). |
| `Dockerfile` / `Dockerfile.job` / `cloudbuild-job.yaml` / `docker-compose.yml` | App image, daily job image, Cloud Build config for the job image, and the local compose setup. |
| `.streamlit/config.toml` | Server config (headless, port 8501, XSRF on). `.streamlit/secrets.toml` is gitignored and holds the `[connections.gcs]` service-account key. |

### Legacy or unused code (not imported by the app; don't extend it)

- `user_heroes.yaml`: old hero lists, superseded by `heroes_lists` in GCS `users.yaml`.
- `2024-09-*.yaml`: old-schema snapshots. They work with `hero_suggestion.py` but **not** with the app (no `winrate_brackets` or `positions`).
- In `scouting_api.py`, `generate_*_markdown()` and `_render_table_image()` are unused. In `pro_meta_api.py`, the `progress_cb` params are unused.
- `load_config()` still falls back to a local `users.yaml` (gitignored, no longer in the repo) when the GCS file is missing. That was a one-time migration path.

---

## External services and data

```
Cloud Scheduler (08:00 Europe/Paris) → Cloud Run Job (fetch_and_upload.py)
    → Stratz GraphQL → gs://heroes-ezdraft/data/YYYY-MM-DD.yaml
Streamlit app (Cloud Run "ezdraft", europe-west1, GCP project "ezdraft")
    ├─ reads  gs://heroes-ezdraft/data/*.yaml        (st.connection FilesConnection, ttl 600s)
    ├─ r/w    gs://heroes-ezdraft/users.yaml          (gcsfs, user_manager)
    ├─ writes gs://heroes-ezdraft/scouting_images/    (shareable scouting PNGs)
    ├─ links  storage.googleapis.com/heroes-ezdraft/icons/<slug>.png  (public hero icons)
    ├─ Stratz GraphQL  (scouting, pro-meta league matches)  — Bearer token, 1 req/s self-throttle
    └─ OpenDota        (league list/info via /explorer SQL, match fallback) — no auth
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

### Users store (`gs://heroes-ezdraft/users.yaml`)

```yaml
credentials: {usernames: {<user>: {name, password (bcrypt), email}}}   # streamlit-authenticator format
cookie: {name, key, expiry_days}
heroes_lists:   {<user>: {<list name>: [<Hero>, ...]}}
scouting_users: [<user>, ...]                     # grants the Scouting tab; edit by hand in GCS
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
- **Pandas Copy-on-Write.** `requirements.txt` allows pandas 3, which enforces CoW, and the Docker build installs the newest allowed version. Writing through `df.values` (for example `np.fill_diagonal(df.values, …)`) silently does nothing there. Use `.at` or `.loc`. The latest commit (`1345ba8`) fixed exactly this. Your local pandas may be 2.x and hide the bug.
- **`streamlit-authenticator` is pinned at 0.3.3** because the app uses that version's API (`authenticator.login('sidebar')` returns a tuple). Newer versions break it. `bcrypt` comes in through this package.
- **Streamlit structure.** The Pro Meta and Scouting tabs are wrapped in `@st.fragment`, so their buttons rerun only the fragment. Use `st.rerun(scope="fragment")` inside them.
  - Fetched results are cached per session in `st.session_state` under `pro_meta_data_<league_id>` and `scout_data_<team>`, each with an ISO `fetched_at`. They are not shared between users.
  - Snapshot processing uses `@st.cache_data`, keyed on the file path.
  - Widget keys are prefixed by tab (`meta_*`, `scout_*`) to avoid collisions. Follow that pattern.
- **Draft dict format** is shared between `pro_meta_api.build_draft_table` and `scouting_api.build_scouting_drafts`: `{match_id, date, radiant, dire, winner, actions: [{order, type: "Pick"|"Ban", hero, icon, side: "Radiant"|"Dire", team}]}`. `draft_to_html()` and `generate_drafts_image()` both consume it.
- **OpenDota fallback matches** have `position: None` and `steamAccountId: None`. The UI hides the `Pos *` columns when they're all zero.
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

Add the username to `scouting_users` in `gs://heroes-ezdraft/users.yaml`. There is no admin UI for this.

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

Deploying is outward-facing, so confirm with the maintainer before running these.

---

## Security notes

- Never commit secrets. `.env`, `.streamlit/secrets.toml` and `.secrets/` are gitignored.
- `.dockerignore` does **not** exclude `.env` or `.streamlit/secrets.toml`, so a local `docker build` bakes them into the image. `gcloud builds submit` respects `.gitignore`.
- The repo is public, and older commits contain expired Stratz tokens and a copy of `users.yaml`. Treat anything ever committed as public.
