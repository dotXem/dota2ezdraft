# dota2ezdraft

Dota 2 hero suggestion tool that helps draft optimal heroes based on enemy and ally team composition. Analyzes hero matchups, synergies, and win rates using data from the Stratz API.

Built with Streamlit, deployed on GCP Cloud Run.

## Setup on a new machine

### Prerequisites

- [Google Cloud CLI (`gcloud`)](https://cloud.google.com/sdk/docs/install)
- Python 3.11+
- Your own Stratz API token, from https://stratz.com/api

### 1. Clone and authenticate

```bash
git clone https://github.com/dotXem/dota2ezdraft.git && cd dota2ezdraft
gcloud auth login
gcloud config set project ezdraft
gcloud auth application-default login   # lets the app use your Google account for GCS
```

The data snapshots are read from the public `heroes-ezdraft` bucket. User accounts live in the private `ezdraft-private` bucket, which your Google account needs access to only if you use the production accounts (see step 2).

### 2. Configure

Create a `.env` file at the repo root:

```bash
STRATZ_API_TOKEN=your_stratz_token
# Optional: keep accounts in a local file instead of the production ones
EZDRAFT_USERS_PATH=users.local.yaml
```

With `EZDRAFT_USERS_PATH` set, sign-ups and hero lists stay on your machine. To see the Scouting tab locally, add your username under `scouting_users:` in that file.

### 3. Install dependencies and run

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

Or with Docker (uses the production accounts; Compose reads the token from `.env`):

```bash
GCS_CREDENTIALS_PATH=$HOME/.config/gcloud/application_default_credentials.json docker compose up
```

## Deployment

See [DEPLOY.md](DEPLOY.md) for Cloud Run deployment instructions.
