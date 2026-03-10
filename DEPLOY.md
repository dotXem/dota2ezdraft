# Deploying EZDraft on GCP Cloud Run

Cloud Run is ideal here — the app already uses a GCS bucket (`heroes-ezdraft`), and Cloud Run can authenticate to it natively via a service account, with no credentials file to manage.

## Prerequisites

- [Google Cloud CLI (`gcloud`)](https://cloud.google.com/sdk/docs/install) installed and authenticated
- A GCP project with billing enabled
- Docker installed locally (or use Cloud Build)

## 1. Initial setup

```bash
# Set your project
export PROJECT_ID=your-gcp-project-id
gcloud config set project $PROJECT_ID

# Enable required APIs
gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com
```

## 2. Create an Artifact Registry repository (one-time)

```bash
gcloud artifacts repositories create ezdraft \
  --repository-format=docker \
  --location=europe-west1 \
  --description="EZDraft Docker images"
```

## 3. Build & push the image

**Option A — Cloud Build (no local Docker needed):**

```bash
gcloud builds submit --tag europe-west1-docker.pkg.dev/$PROJECT_ID/ezdraft/streamlit-app
```

**Option B — Build locally & push:**

```bash
gcloud auth configure-docker europe-west1-docker.pkg.dev
docker build -t europe-west1-docker.pkg.dev/$PROJECT_ID/ezdraft/streamlit-app .
docker push europe-west1-docker.pkg.dev/$PROJECT_ID/ezdraft/streamlit-app
```

## 4. Ensure GCS access

The default Cloud Run service account (`PROJECT_NUMBER-compute@developer.gserviceaccount.com`) needs read/write access to the `heroes-ezdraft` bucket:

```bash
gcloud storage buckets add-iam-policy-binding gs://heroes-ezdraft \
  --member="serviceAccount:$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')-compute@developer.gserviceaccount.com" \
  --role="roles/storage.objectAdmin"
```

## 5. Set the Stratz API token as a secret

```bash
echo -n "YOUR_STRATZ_API_TOKEN" | gcloud secrets create stratz-api-token --data-file=-

# Grant the Cloud Run service account access to the secret
gcloud secrets add-iam-policy-binding stratz-api-token \
  --member="serviceAccount:$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

## 6. Deploy to Cloud Run

```bash
gcloud run deploy ezdraft \
  --image europe-west1-docker.pkg.dev/$PROJECT_ID/ezdraft/streamlit-app \
  --region europe-west1 \
  --port 8501 \
  --allow-unauthenticated \
  --memory 512Mi \
  --min-instances 0 \
  --max-instances 3 \
  --set-secrets=STRATZ_API_TOKEN=stratz-api-token:latest
```

Cloud Run gives you a public URL like `https://ezdraft-xxxxx-ew.a.run.app`. Done!

## Updating the app

After code changes, rebuild and redeploy:

```bash
# Build new image
gcloud builds submit --tag europe-west1-docker.pkg.dev/$PROJECT_ID/ezdraft/streamlit-app

# Deploy updated image
gcloud run deploy ezdraft \
  --image europe-west1-docker.pkg.dev/$PROJECT_ID/ezdraft/streamlit-app \
  --region europe-west1
```

## Useful commands

```bash
# View logs
gcloud run services logs read ezdraft --region europe-west1

# Check service status
gcloud run services describe ezdraft --region europe-west1

# Delete the service
gcloud run services delete ezdraft --region europe-west1
```

## Optional: Custom domain

```bash
gcloud run domain-mappings create \
  --service ezdraft \
  --domain yourdomain.com \
  --region europe-west1
```

Then add the DNS records shown in the output. Cloud Run handles HTTPS automatically.

## Optional: Daily data fetch cron job

A Cloud Run Job + Cloud Scheduler can fetch Stratz data automatically every day.

### 1. Build the job image

```bash
gcloud builds submit --tag europe-west1-docker.pkg.dev/$PROJECT_ID/ezdraft/fetch-job -f Dockerfile.job
```

### 2. Create the Cloud Run Job

```bash
gcloud run jobs create ezdraft-fetch \
  --image europe-west1-docker.pkg.dev/$PROJECT_ID/ezdraft/fetch-job \
  --region europe-west1 \
  --memory 512Mi \
  --task-timeout 600 \
  --set-secrets=STRATZ_API_TOKEN=stratz-api-token:latest
```

### 3. Schedule it daily with Cloud Scheduler

```bash
gcloud scheduler jobs create http ezdraft-daily-fetch \
  --location europe-west1 \
  --schedule "0 8 * * *" \
  --time-zone "Europe/Paris" \
  --uri "https://europe-west1-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT_ID/jobs/ezdraft-fetch:run" \
  --http-method POST \
  --oauth-service-account-email $(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')-compute@developer.gserviceaccount.com
```

This runs every day at 8:00 AM Paris time. To change the schedule, edit the cron expression.

### Useful commands

```bash
# Run the job manually
gcloud run jobs execute ezdraft-fetch --region europe-west1

# View job executions
gcloud run jobs executions list --job ezdraft-fetch --region europe-west1

# View logs
gcloud run jobs logs read ezdraft-fetch --region europe-west1

# Update the job image after code changes
gcloud builds submit --tag europe-west1-docker.pkg.dev/$PROJECT_ID/ezdraft/fetch-job -f Dockerfile.job
gcloud run jobs update ezdraft-fetch \
  --image europe-west1-docker.pkg.dev/$PROJECT_ID/ezdraft/fetch-job \
  --region europe-west1
```

## Local development

For local development, use docker-compose (requires a GCS credentials file):

```bash
mkdir -p .secrets
# Place your service account key at .secrets/gcs_credentials.json
export STRATZ_API_TOKEN=your_stratz_token_here
docker compose up --build
# App available at http://localhost:8501
```
