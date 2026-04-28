# Sports Media Protection — Cloud Run Dockerfile
# Build context: project root (sports-media-protection/)
# Deploy: gcloud run deploy smp-api --source . --region us-central1

FROM python:3.11-slim

# System deps: ffmpeg (video processing), chromaprint (audio fingerprinting)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libchromaprint-tools \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# PyTorch CPU wheel first — separate layer so it stays cached on re-builds
RUN pip install --no-cache-dir \
    torch==2.3.0 \
    torchvision==0.18.0 \
    --index-url https://download.pytorch.org/whl/cpu

# Python dependencies
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Backend source
COPY backend/src/ ./src/

# Frontend (served as static files at / and /ui by FastAPI)
COPY frontend/ ./frontend/

# Runtime data dirs — writable on Cloud Run ephemeral disk
# Data is lost on container restart; use GCS mount for persistence (see docs)
RUN mkdir -p /app/data/originals /app/data/frames /app/data/indices /app/data/reports

# Cloud Run injects $PORT (default 8080). Never hardcode the port.
EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn src.main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1"]
