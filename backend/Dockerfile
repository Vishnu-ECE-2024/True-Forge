FROM python:3.11-slim

# System deps: ffmpeg for video processing, fpcalc for audio fingerprinting
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libchromaprint-tools \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install PyTorch CPU-only wheel first (separate layer for cache efficiency).
# CPU build is ~250 MB vs ~2 GB for the CUDA build.
# To enable GPU: change 'cpu' → 'cu121' and match your CUDA version.
RUN pip install --no-cache-dir \
    torch==2.3.0 \
    torchvision==0.18.0 \
    --index-url https://download.pytorch.org/whl/cpu

# Install remaining Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY src/ ./src/

# Create data dirs (also mapped as volumes)
RUN mkdir -p /app/data/originals /app/data/frames /app/data/indices /app/data/reports

EXPOSE 8000

# Reads $PORT if set (Cloud Run compatibility), falls back to 8000 for local dev
CMD ["sh", "-c", "exec uvicorn src.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
