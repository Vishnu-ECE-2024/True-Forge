# Sports Media Protection — True Forge

Detect unauthorized redistribution of sports video content.
Register originals, fingerprint them, then search for matches across suspected copies.
Powered by Google Gemini for AI-assisted content analysis.

---

## Deploy to Google Cloud (primary path)

```bash
# From project root
export GCP_PROJECT=your-project-id
export GCP_REGION=us-central1

# One command — Cloud Build picks up the top-level Dockerfile
gcloud run deploy smp-api \
  --source . \
  --region $GCP_REGION \
  --allow-unauthenticated \
  --memory 2Gi --cpu 2 \
  --min-instances 1 \
  --set-env-vars "DATABASE_URL=postgresql+psycopg2://smp_user:PASSWORD@/smp_db?host=/cloudsql/PROJECT:REGION:INSTANCE" \
  --set-secrets "GOOGLE_API_KEY=GOOGLE_API_KEY:latest"
```

Full step-by-step: **`docs/GOOGLE_CLOUD_DEPLOY.md`**

---

## Local development

```bash
cp .env.example .env        # fill in GOOGLE_API_KEY
make up                     # starts postgres + backend
# open http://localhost:8000
```

## Architecture

```
Browser (single-page HTML)
        │
        ▼
FastAPI + frontend (port 8000 / Cloud Run $PORT)
  ├── POST /api/assets/upload     → save + queue fingerprinting
  ├── POST /api/search/upload     → match suspect video against originals
  ├── POST /api/watermark/embed   → embed invisible DCT watermark
  ├── POST /api/monitor/submit    → download URL + match via yt-dlp
  └── GET  /api/health, /api/stats/

  Background (FastAPI BackgroundTasks)
    └── FFmpeg → pHash + MobileNetV3 DL embedding + Chromaprint audio
                ↓
           Gemini 2.0 Flash AI analysis (sport type, confidence, teams)
                ↓
           FAISS vector index + PostgreSQL
```

## Core flows

| Flow | Endpoint | What happens |
|------|----------|-------------|
| Register original | `POST /api/assets/upload` | Fingerprint + Gemini analysis |
| Find copies | `POST /api/search/upload` | Fusion search: pHash + DL + audio |
| Watermark | `POST /api/watermark/{id}/embed` | Embed invisible DCT watermark |
| URL check | `POST /api/monitor/submit` | yt-dlp download + match |
| Health | `GET /api/health` | DB + FAISS status |

## Make commands

| Command | What it does |
|---------|-------------|
| `make up` | Start Docker Compose (postgres + backend) |
| `make down` | Stop everything |
| `make logs` | Tail backend logs |
| `make test` | Run pytest suite |
| `make shell` | Bash inside backend container |

## Configuration

See `.env.example` for all variables. Key ones:

```
GOOGLE_API_KEY=          # Required for Gemini AI analysis
MATCH_THRESHOLD=0.85     # Similarity cutoff (0.0–1.0)
FRAME_SAMPLE_RATE=1      # Frames/sec sampled for fingerprinting
MAX_VIDEO_SIZE_MB=200    # Upload size limit
```

## Docs

- `docs/GOOGLE_CLOUD_DEPLOY.md` — Cloud Run + Cloud SQL deployment guide
- `docs/WEB_PROTOTYPE_STATUS.md` — Working flows, demo script, known limits
- `http://localhost:8000/docs` — Swagger API reference (when running)
