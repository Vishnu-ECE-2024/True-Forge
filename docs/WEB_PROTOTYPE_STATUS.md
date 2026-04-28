# Web Prototype Status — Sports Media Protection (True Forge)

Last updated: 2026-04-28

---

## What is this

True Forge is a sports media copyright protection prototype. It fingerprints original video
content using multi-modal signals, detects unauthorized copies, embeds invisible watermarks,
and provides AI-assisted evidence analysis powered by Google Gemini.

The deliverable is a **hosted web application** on Google Cloud Run.

---

## Working flows

### 1. Asset registration (Upload + Index)
- Upload a video or image via the web UI
- Backend extracts frames, computes pHash (256-bit), DL embedding (MobileNetV3-Small 576-dim), and audio fingerprint (Chromaprint)
- Gemini 2.0 Flash analyzes sampled frames: classifies sport type, confidence, scene descriptions
- All data saved to PostgreSQL + FAISS vector index
- Status polling: upload returns `asset_id`; re-fetch `/api/assets/{id}` to check `processing → ready`

### 2. Search / match detection
- Upload a suspected video via the web UI (Search tab)
- Backend runs the same pipeline on the suspect file (no storage)
- Fusion score combines pHash + DL embedding + audio similarity
- Returns ranked results with: similarity %, match type (exact / near-duplicate / partial), verdict (MATCH / POSSIBLE_MATCH / NO_MATCH)
- Results display Gemini AI tag showing sport type + classification from the matched original

### 3. Watermark
- Embed: applies DCT-based invisible watermark to a registered video
- Detect: upload any video to check if it contains one of our registered watermarks
- Both operations run server-side; no client-side processing

### 4. URL monitoring
- Submit a URL (YouTube, direct video link) for checking
- Backend downloads via yt-dlp and runs the full search pipeline
- Results appear in the Alerts tab as match alerts with similarity scores
- Requires network egress from Cloud Run (available by default)

### 5. Dashboard / Stats
- Shows: total indexed assets, match alerts, watermarked assets, daily alert chart
- Pulls from live PostgreSQL data

### 6. Gemini AI — where it appears
- During asset registration: Gemini analyzes extracted frames, stores `overall_classification`, `sport_type`, `confidence`, `scene_descriptions`, `teams` in the asset record
- In search results: each matched asset shows a "✦ Gemini AI" badge with its classification and confidence
- In asset library: Gemini metadata shown per asset
- Fails gracefully when `GOOGLE_API_KEY` is absent — system still works with pHash/DL/audio only

---

## Known limitations (prototype)

| Limitation | Impact | Production fix |
|-----------|--------|----------------|
| FAISS index is in-memory / ephemeral disk | Index resets on container restart; Cloud SQL metadata preserved | Mount GCS bucket for index files |
| Uploaded video files are ephemeral | Videos lost on restart | GCS bucket for `/app/data/originals` |
| Single Cloud Run instance (min=1) | One concurrent user pipeline at a time | Add task queue (Cloud Tasks) |
| No authentication | Any user can upload/delete | Add Google OAuth or API key gate |
| yt-dlp subject to platform changes | Monitor flow may fail on some URLs | Keep yt-dlp pinned and updated |
| DL model (MobileNetV3) downloads on cold start | ~30s first-start latency | Bake weights into Docker image |
| Max video size 200 MB on Cloud Run deploy | Large sports broadcasts need chunked upload | Increase Cloud Run memory; use signed GCS upload |

---

## Demo script (5-minute walkthrough)

1. Open `https://YOUR-CLOUD-RUN-URL`
2. **Upload** a short sports clip (mp4, < 50 MB) → wait for status to show "ready"
3. **Library tab** — see the asset with Gemini AI classification badge
4. **Search tab** → upload the same clip (or a lightly edited copy) → see MATCH result with fusion score and Gemini tag
5. **Watermark tab** → embed watermark on the registered asset → upload any copy → detect confirms watermark
6. **Dashboard tab** → see live stats update

---

## Submission claims (verifiable)

- Deployed on Google Cloud Run ✓
- Uses Google AI (Gemini 2.0 Flash) ✓
- Real media protection workflow: register → fingerprint → match ✓
- Multi-modal fingerprinting: visual pHash + DL embeddings + audio ✓
- PostgreSQL metadata persistence via Cloud SQL ✓
