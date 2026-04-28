# Google Cloud Deployment — Sports Media Protection

Deploys a single Cloud Run service (FastAPI + embedded frontend) backed by Cloud SQL for PostgreSQL.

---

## Prerequisites

```bash
# Install gcloud CLI and authenticate
gcloud auth login
gcloud auth configure-docker

# Set your project
export GCP_PROJECT=your-project-id
export GCP_REGION=us-central1
export SERVICE_NAME=smp-api

gcloud config set project $GCP_PROJECT
```

Required APIs (enable once):
```bash
gcloud services enable \
  run.googleapis.com \
  sqladmin.googleapis.com \
  secretmanager.googleapis.com \
  cloudbuild.googleapis.com
```

---

## Step 1 — Create Cloud SQL (PostgreSQL)

```bash
# Create instance (~3 min first time)
gcloud sql instances create smp-db \
  --database-version=POSTGRES_16 \
  --tier=db-f1-micro \
  --region=$GCP_REGION \
  --storage-auto-increase

# Create database and user
gcloud sql databases create smp_db --instance=smp-db
gcloud sql users create smp_user \
  --instance=smp-db \
  --password=CHANGE_THIS_PASSWORD

# Get connection name (format: PROJECT:REGION:INSTANCE)
gcloud sql instances describe smp-db --format="value(connectionName)"
# Save this — you'll use it as CLOUD_SQL_CONNECTION_NAME
```

---

## Step 2 — Store secrets in Secret Manager

```bash
# Google AI key
echo -n "your-google-api-key" | \
  gcloud secrets create GOOGLE_API_KEY --data-file=-

# Database password
echo -n "CHANGE_THIS_PASSWORD" | \
  gcloud secrets create DB_PASSWORD --data-file=-
```

---

## Step 3 — Deploy to Cloud Run

Run from the **project root** (`sports-media-protection/`):

```bash
CLOUD_SQL_CONNECTION_NAME=$(gcloud sql instances describe smp-db \
  --format="value(connectionName)")

gcloud run deploy $SERVICE_NAME \
  --source . \
  --region $GCP_REGION \
  --platform managed \
  --allow-unauthenticated \
  --memory 2Gi \
  --cpu 2 \
  --timeout 300 \
  --concurrency 4 \
  --min-instances 1 \
  --add-cloudsql-instances $CLOUD_SQL_CONNECTION_NAME \
  --set-env-vars "DATABASE_URL=postgresql+psycopg2://smp_user:CHANGE_THIS_PASSWORD@/smp_db?host=/cloudsql/${CLOUD_SQL_CONNECTION_NAME}" \
  --set-env-vars "GOOGLE_AI_ENABLED=true" \
  --set-env-vars "GEMINI_MODEL=gemini-2.0-flash" \
  --set-env-vars "MATCH_THRESHOLD=0.85" \
  --set-env-vars "FRAME_SAMPLE_RATE=1" \
  --set-env-vars "HASH_SIZE=16" \
  --set-env-vars "MAX_VIDEO_SIZE_MB=200" \
  --set-env-vars "LOG_LEVEL=WARNING" \
  --set-secrets "GOOGLE_API_KEY=GOOGLE_API_KEY:latest"
```

The `--source .` flag uses Cloud Build to build the top-level `Dockerfile` automatically.

After deploy, get your URL:
```bash
gcloud run services describe $SERVICE_NAME \
  --region $GCP_REGION \
  --format "value(status.url)"
```

Set CORS to your Cloud Run URL (re-deploy with):
```bash
SERVICE_URL=$(gcloud run services describe $SERVICE_NAME \
  --region $GCP_REGION --format "value(status.url)")

gcloud run services update $SERVICE_NAME \
  --region $GCP_REGION \
  --set-env-vars "ALLOWED_ORIGINS=${SERVICE_URL}"
```

---

## Step 4 — Verify deployment

```bash
# Health check
curl https://YOUR-SERVICE-URL/api/health

# Expected:
# {"status":"ok","database":"ok","faiss_index":"ok (0 vectors)",...}
```

Open `https://YOUR-SERVICE-URL` in a browser — the web app should load.

---

## Required environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL connection string (Cloud SQL socket or standard URL) |
| `GOOGLE_API_KEY` | Yes | Google AI Studio key for Gemini |
| `GOOGLE_AI_ENABLED` | No | `true` / `false` (default `true`) |
| `GEMINI_MODEL` | No | `gemini-2.0-flash` (default) |
| `ALLOWED_ORIGINS` | No | CORS — set to your Cloud Run URL |
| `MATCH_THRESHOLD` | No | Similarity cutoff, default `0.85` |
| `MAX_VIDEO_SIZE_MB` | No | Upload size limit, default `500` |
| `FRAME_SAMPLE_RATE` | No | Frames/sec for fingerprinting, default `1` |
| `LOG_LEVEL` | No | `INFO` or `WARNING` |

---

## Cloud Run service account permissions

The Cloud Run service account needs:
- `Cloud SQL Client` — to connect to Cloud SQL
- `Secret Manager Secret Accessor` — to read `GOOGLE_API_KEY` from Secret Manager

```bash
# Get the service account
SA=$(gcloud run services describe $SERVICE_NAME \
  --region $GCP_REGION \
  --format "value(spec.template.spec.serviceAccountName)")

# Grant Cloud SQL access
gcloud projects add-iam-policy-binding $GCP_PROJECT \
  --member "serviceAccount:$SA" \
  --role roles/cloudsql.client

# Grant Secret Manager access
gcloud projects add-iam-policy-binding $GCP_PROJECT \
  --member "serviceAccount:$SA" \
  --role roles/secretmanager.secretAccessor
```

---

## Known prototype limitations

See `docs/WEB_PROTOTYPE_STATUS.md` for full details.

**Key constraint:** FAISS vector indices and uploaded video files live on the container's ephemeral disk. They persist as long as the container instance runs (min-instances=1 keeps it alive). A container restart resets them — metadata in Cloud SQL is preserved but the FAISS index rebuilds empty.

**For a persistent production deployment**, add a Cloud Storage bucket and mount it via Cloud Run's volume feature, or implement GCS-backed index save/load.

---

## Local development

```bash
# Start everything with Docker Compose
cp .env.example .env
# Fill in GOOGLE_API_KEY in .env
make up

# App available at:
# http://localhost:8000   (API + frontend via FastAPI)
# http://localhost:80     (nginx proxy, prod compose)
# http://localhost:8000/docs  (Swagger UI)
```

## Re-deploy after changes

```bash
# From project root
gcloud run deploy $SERVICE_NAME --source . --region $GCP_REGION
```
