# dota2ezdraft

Dota 2 hero suggestion tool that helps draft optimal heroes based on enemy and ally team composition. Analyzes hero matchups, synergies, and win rates using data from the Stratz API.

Built with Streamlit, deployed on GCP Cloud Run.

## Setup on a new machine

### Prerequisites

- [Google Cloud CLI (`gcloud`)](https://cloud.google.com/sdk/docs/install)
- Python 3.11+

### 1. Clone and authenticate

```bash
git clone <repo-url> && cd dota2ezdraft
gcloud auth login
gcloud config set project ezdraft
```

### 2. Pull local dev secrets

```bash
mkdir -p .streamlit
gcloud secrets versions access latest --secret=streamlit-local-secrets > .streamlit/secrets.toml
```

### 3. Install dependencies and run

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

Or with Docker:

```bash
docker compose up
```

## Deployment

See [DEPLOY.md](DEPLOY.md) for Cloud Run deployment instructions.

## Updating the local dev secrets

If you rotate the GCS service account key, update the secret:

```bash
gcloud secrets versions add streamlit-local-secrets --data-file=.streamlit/secrets.toml
```