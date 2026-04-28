#!/usr/bin/env bash
# Setup script for Sports Media Protection System
# Tested on Ubuntu 24.04 LTS

set -euo pipefail

echo "=== Sports Media Protection — Setup ==="

# 1. Check required tools
for cmd in docker curl; do
  if ! command -v "$cmd" &>/dev/null; then
    echo "ERROR: '$cmd' not found. Install it and re-run."
    exit 1
  fi
done

# Check Docker Compose v2
if ! docker compose version &>/dev/null; then
  echo "ERROR: Docker Compose v2 not found. Install docker-compose-plugin."
  exit 1
fi

echo "✓ Docker and Docker Compose found"

# 2. Create .env if missing
if [ ! -f .env ]; then
  cp .env.example .env
  echo "✓ Created .env from .env.example"
  echo "  → Edit .env to change passwords before production use"
else
  echo "✓ .env already exists"
fi

# 3. Create data directories
mkdir -p data/originals data/frames data/indices
echo "✓ Data directories ready"

# 4. Build and start
echo ""
echo "Starting services (this may take a few minutes on first run)..."
docker compose up --build -d

# 5. Wait for backend
echo "Waiting for API to be ready..."
for i in $(seq 1 30); do
  if curl -sf http://localhost:8000/api/health > /dev/null 2>&1; then
    echo "✓ API is ready"
    break
  fi
  sleep 2
  echo "  Waiting... ($i/30)"
done

echo ""
echo "=== Setup Complete ==="
echo ""
echo "  API:      http://localhost:8000/api"
echo "  Docs:     http://localhost:8000/docs"
echo "  Frontend: http://localhost:8000/ui"
echo ""
echo "Useful commands:"
echo "  make logs    — watch service logs"
echo "  make down    — stop all services"
echo "  make test    — run tests"
echo "  make shell   — open backend shell"
