# Architecture Analysis: Digital Sports Media Protection System

## 1. Problem Understanding

**Real problem:** A solo student developer needs to detect when sports video content is
redistributed without authorization on platforms like YouTube, TikTok, or Telegram.

**Core workflow:**
1. Owner uploads original video → system fingerprints it
2. Suspected copy found → system compares fingerprint → returns match confidence

**Actual users:** 1 operator (you), possibly small regional sports org later.
**Scale:** 100–500 uploads/month = ~6,000 videos/year. This is tiny.

---

## 2. Solution Understanding (Proposed)

The proposed design is a 5-service Docker Compose stack:
- FastAPI (backend)
- PostgreSQL (metadata)
- Milvus (vector store)
- Redis (job queue)
- DINOv2 + PANNs (fingerprint models)

With 5 phases covering ingestion → watermarking → web crawling → AI decision → dashboard.

---

## 3. Alignment Review

**Weakly aligned in several places:**

| Proposed | Problem Fit | Verdict |
|---|---|---|
| DINOv2 (ViT-L) for fingerprinting | 200ms/frame CPU → 5min/video | Overkill for v1 |
| Milvus vector DB | 3 Docker containers just for DB | Overkill at 6k videos |
| PANNs audio model | 500MB model, slow CPU | Overkill vs Chromaprint |
| Redis queue | Needed only at scale | Premature |
| VideoSeal watermarks | Research-grade, GPU-hungry | Phase 2+ only |
| Web crawlers (Phase 3) | Legal gray area, API-fragile | Dangerous |
| LightGBM classifier | Needs labeled dataset you don't have | Phase 4+ |
| Next.js frontend | 200MB node_modules for a dashboard | Overkill |

---

## 4. Overengineering / Risk Analysis

### GPU Risks
- DINOv2 ViT-L: 307M params. CPU inference = 200ms/frame. Acceptable overnight.
- PANNs: Adds complexity with no benefit over Chromaprint for fingerprinting.
- VideoSeal: GPU-only in practice. Skip for v1.

### Infrastructure Risks
- **Milvus** requires 3 sub-services (etcd, minio, milvus). 6GB RAM baseline.
  → Replace with **FAISS** (in-process, zero infra) or **Qdrant** (single Docker container).
- **Redis** is premature when FastAPI background tasks handle async jobs fine for 1 operator.

### Legal Risks
- Crawling YouTube/TikTok violates ToS. YouTube Data API has quotas.
- For v1: accept manual URL submission from operator. Add crawler in Phase 3.

### Missing Items
- No SHA256 deduplication before fingerprinting (duplicate uploads waste compute)
- No frame sampling strategy documented (every frame = 30×30 = 900 hashes/second!)
- No match threshold tuning guide

---

## 5. Practical Architecture (3 Tiers)

### Tier 1 — MVP Laptop System (BUILD THIS NOW)
```
FastAPI + PostgreSQL + FAISS + pHash + Chromaprint + Vanilla HTML frontend
Docker Compose: 2 services (postgres + backend)
```
- Visual: imagehash pHash on 1 frame/second sample → stored as int array
- Audio: fpcalc (Chromaprint) → 32-bit integer array  
- Search: FAISS flat L2 index, persisted to disk
- Frontend: single index.html (vanilla JS, mobile-responsive)
- Queue: FastAPI BackgroundTasks (no Redis)
- DB: PostgreSQL (or SQLite for offline dev)

**Performance:** 1 video/min on CPU. 100 videos = 100 min. Overnight = fine.
**RAM:** ~500MB total. Works on 8GB laptop.
**Storage:** ~50MB per hour of video (frames cached, then deleted).

### Tier 2 — Stronger Single-Machine (After Tier 1 works)
```
Add: DINOv2 visual embeddings, Qdrant, Redis queue, better frontend
```
- Replace pHash with DINOv2 ViT-S/8 (smaller model, still good)
- Replace FAISS with Qdrant (persistent, filterable)
- Add Redis + Celery for background jobs
- Frontend: React or Next.js (if needed)

### Tier 3 — Production Multi-Service (If project succeeds)
```
Add: Milvus, horizontal workers, VideoSeal, web monitoring, cloud deployment
```

---

## 6. Recommended Stack for Tier 1

| Component | Choice | Why |
|---|---|---|
| Backend | FastAPI 0.111 | Async, type-safe, fast |
| DB | PostgreSQL 16 | Reliable, you already know SQL |
| Vector Search | FAISS-cpu | Zero infra, in-process, exact search fine at <10k |
| Visual FP | imagehash pHash | 1ms/frame on CPU, good near-dupe detection |
| Audio FP | fpcalc (Chromaprint) | Industry standard (used by MusicBrainz) |
| Video | FFmpeg | Non-negotiable |
| Frontend | Vanilla HTML + Tailwind CDN | Zero build step, mobile-ready |
| Containers | Docker Compose v2 | 2 services only |
| Config | Pydantic Settings v2 | Type-safe env vars |

---

## 7. Future Upgrades (Document, Don't Build Yet)

- **Phase 1.5:** DINOv2 ViT-S/8 embeddings alongside pHash
- **Phase 2:** VideoSeal watermarks (GPU recommended)
- **Phase 3:** YouTube Data API v3 integration (not scraping)
- **Phase 4:** LightGBM classifier (after you have labeled match data)
- **Phase 5:** Qdrant + React frontend + cloud deployment
