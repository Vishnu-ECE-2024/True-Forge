# True Forge — Change Report & System State
**Date:** 2026-04-27  
**Session focus:** Image support across all clients + app rename to True Forge

---

## 1. CHANGES MADE THIS SESSION

### 1.1 Image Support — Android App (7 files)

#### `util/FileUtils.kt`
- Added `getMimeType(context, uri)` — reads MIME type from ContentResolver
- Added `isImageUri(context, uri)` — returns true for `image/*` MIME types
- Added `loadBitmapFromUri(context, uri)` — decodes image to Bitmap via BitmapFactory
- Fixed `uriToMultipartPart` — was hardcoded to `"video/*"`, now uses actual MIME type (fixes image uploads to server)

#### `data/local/LocalEntities.kt`
- Added `isImage()` extension on `LocalAsset` — checks filename extension against `{jpg, jpeg, png, webp, gif, bmp, heic, heif}`

#### `data/repository/AssetRepository.kt`
- `registerLocally()` now branches:
  - **Image:** decode bitmap directly → single pHash → skip audio fingerprint → `durationSeconds = null`
  - **Video:** extract frames (max 30) → multi-frame pHash → compute audio fingerprint (unchanged)

#### `data/repository/SearchRepository.kt`
- `searchLocally()` now branches:
  - **Image:** decode bitmap → single pHash → skip audio → search LocalSearchEngine
  - **Video:** extract frames → multi-frame pHash → audio → search (unchanged)

#### `data/repository/WatermarkRepository.kt`
- `embedLocalWatermark()`: images load bitmap directly via `FileUtils.loadBitmapFromUri` instead of frame extraction
- `detectLocalWatermark()`: images call `watermarkEngine.detectInBitmap()` directly (1 frame) instead of `detectInFrames()`

#### `ui/screens/assets/AssetsScreen.kt`
- FAB replaced with expandable FAB pattern:
  - Single tap → expands showing two mini-FABs: **Movie icon (Video)** and **Image icon (Image)**
  - Each launches `GetContent` with respective MIME type (`video/*` / `image/*`)
  - Tap again or pick file → collapses
- Empty state text updated: "video" → "video or image"

#### `ui/screens/search/SearchScreen.kt`
- Upload card now has two side-by-side buttons instead of one: **Video** | **Image**
- Description updated: "suspect video" → "suspect video or image"
- Added `Icons.Filled.Movie` and `Icons.Filled.Image` imports

#### `ui/screens/watermark/WatermarkScreen.kt`
- Detect section now has two side-by-side buttons: **Video** | **Image**
- Description updated: "video" → "video or image"
- Two separate launchers (`detectVideoPicker`, `detectImagePicker`) both call `vm.detectWatermark(uri)`

---

### 1.2 Image Support — Backend (6 files)

#### `fingerprint/visual.py`
- Added `IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".heic", ".heif"}`
- Added `is_image(path)` helper
- Added `hash_image_directly(image_path)` — opens image with PIL, computes pHash, returns same `np.ndarray` format as `compute_visual_fingerprint` (float32, HASH_BITS=256 length)

#### `fingerprint/pipeline.py`
- Added `process_image_asset(asset_id, image_path, faiss_index, dl_index)`:
  - Sets status → PROCESSING
  - Calls `hash_image_directly()` — no FFmpeg, no audio
  - Adds vector to FAISS pHash index
  - Sets `duration_seconds=None`, `frame_count=1`, `audio_fingerprint=None`
  - Sets status → READY

#### `api/assets.py`
- Split `ALLOWED_EXTENSIONS` into `VIDEO_EXTENSIONS | IMAGE_EXTENSIONS` (now accepts `.jpg .jpeg .png .webp .gif .bmp .heic .heif` in addition to video)
- Upload endpoint now dispatches:
  - `process_image_asset` for image files
  - `process_asset` for video files (unchanged)

#### `api/search.py`
- Added `IMAGE_EXTENSIONS` import, expanded `ALLOWED_EXTENSIONS`
- Added `_search_by_image_fingerprint(image_path, faiss_index, dl_index, db)`:
  - Calls `hash_image_directly()` → searches pHash FAISS index
  - No audio, no DL embedding for images
  - Returns same `SearchResult` format
- `search_by_upload` endpoint now branches on image vs video extension

#### `watermark/dct.py`
- Added `embed_watermark_in_image(input_path, output_path, asset_id)`:
  - Reads image with OpenCV
  - Embeds DWT-DCT watermark (same `dwtDct` method as video)
  - Writes watermarked image to output_path
- Added `detect_watermark_in_image(image_path, known_asset_ids)`:
  - Reads image with OpenCV
  - Runs single-frame watermark decode
  - Returns same `{detected, asset_id, confidence, frames_checked}` dict as video version

#### `api/watermark.py`
- `_do_embed()` background task: detects image vs video from extension, calls `embed_watermark_in_image` or `embed_watermark_video`, sets correct output filename (`watermarked{ext}` for images vs `watermarked.mp4`)
- `detect_watermark` endpoint: detects image vs video from extension, calls appropriate function

---

### 1.3 Image Support — Desktop App (3 files)

#### `ui/assets_page.py`
- Button label: "Upload Video" → "Upload Asset"
- File dialog filter: video-only → `Media Files (*.mp4 *.mkv *.avi *.mov *.webm *.ts *.flv *.jpg *.jpeg *.png *.webp *.gif *.bmp *.heic *.heif)`

#### `ui/search_page.py`
- Card title: "Find Video Matches" → "Find Video or Image Matches"
- Placeholder: "Select a video file…" → "Select a video or image file…"
- File dialog: video-only → media files (same filter as above)

#### `ui/watermark_page.py`
- Placeholder: "Select video to analyze…" → "Select video or image to analyze…"
- File dialog: video-only → media files (same filter as above)

---

### 1.4 Image Support — Frontend (1 file)

#### `frontend/index.html`
- Upload drop zone: `accept="video/*"` → `accept="video/*,image/*"`
- Upload help text: "MP4, MKV, AVI, MOV, WebM" → "MP4, MKV, MOV, WebM · JPG, PNG, WEBP"
- Upload drop zone label: "Drag & drop your video here" → "Drag & drop your video or image here"
- Search drop zone: `accept="video/*"` → `accept="video/*,image/*"`
- Search drop zone label: "Drop suspected video here" → "Drop suspected video or image here"
- Search page description updated

---

### 1.5 App Rename: "Sports Media Protection" / "SMP" → "True Forge"

#### `desktop-app/ui/main_window.py`
- Window title: `"Sports Media Protection"` → `"True Forge"`
- QSettings org: `"SMP"` → `"TrueForge"`
- Sidebar logo title: `"SMP"` → `"True Forge"` (font size adjusted 22px → 18px)
- Sidebar subtitle: `"Sports Media Protection"` → `"Media Protection Platform"`

#### `frontend/index.html`
- `<title>`: `"Sports Media Protection"` → `"True Forge"`
- Sidebar logo text: `"SMP"` → `"True Forge"` (×2 occurrences)
- Footer engine text: `"SMP protection engine"` → `"True Forge protection engine"`

---

## 2. PENDING ACTION REQUIRED

**The backend Docker container must be restarted to apply the image support changes:**

```bash
cd /home/vishnu/sports-media-protection
docker compose restart
# or full rebuild:
docker compose up -d --build
```

Without this, the server still rejects `.png` and other image types with HTTP 400.

---

## 3. CURRENT FULL SYSTEM STATE

### 3.1 Project Identity
- **Name:** True Forge
- **Purpose:** Self-hosted copyright protection platform for sports video and image content
- **Root path:** `/home/vishnu/sports-media-protection/`

---

### 3.2 Backend — FastAPI

**Path:** `/home/vishnu/sports-media-protection/backend/`  
**Start:** `docker compose up -d` (from root)  
**URL:** `http://localhost:8000`  
**Docs:** `http://localhost:8000/docs`

#### Stack
| Component | Technology |
|---|---|
| API framework | FastAPI (Python) |
| Database | PostgreSQL 16 (Docker) |
| Vector search | FAISS (flat index, 256-bit pHash vectors) |
| Visual fingerprint | imagehash pHash (hash_size=16) |
| DL embedding | MobileNetV3-Small (optional, secondary FAISS index) |
| Audio fingerprint | Chromaprint |
| AI analysis | Gemini 2.0 Flash (Google AI, optional) |
| Watermarking | invisible-watermark (DWT-DCT-SVD, 32-byte payload) |

#### API Endpoints
| Method | Path | Description |
|---|---|---|
| POST | `/api/assets/upload` | Upload video or image → fingerprint queued |
| GET | `/api/assets/` | List all assets |
| GET | `/api/assets/{id}` | Asset details |
| DELETE | `/api/assets/{id}` | Delete asset |
| POST | `/api/search/upload` | Search by uploading video or image |
| POST | `/api/search/asset/{id}` | Search using stored asset |
| POST | `/api/watermark/{id}/embed` | Embed watermark into asset |
| POST | `/api/watermark/detect` | Detect watermark in uploaded file |
| GET | `/api/watermark/{id}` | Watermark status |
| POST | `/api/monitor/submit` | Submit URL for monitoring |
| GET | `/api/monitor/jobs` | List monitoring jobs |
| GET | `/api/monitor/alerts` | List alerts |
| PATCH | `/api/monitor/alerts/{id}/review` | Mark alert reviewed |
| GET | `/api/reports/{id}` | Report JSON |
| GET | `/api/reports/{id}/html` | Report HTML |
| GET | `/api/stats` | System KPIs |
| GET | `/api/health` | Health check |
| GET | `/api/system-info` | System info |
| POST | `/api/ingest/batch` | Batch ingest |
| POST | `/api/ingest/url` | Ingest from URL |

#### Accepted File Types
| Category | Extensions |
|---|---|
| Video | `.mp4 .mkv .avi .mov .webm .ts .flv` |
| Image | `.jpg .jpeg .png .webp .gif .bmp .heic .heif` |

#### Fingerprinting Pipeline
- **Video:** Duration probe → FFmpeg frame extraction → pHash (parallel threads) → Gemini AI analysis (optional) → MobileNetV3 DL embedding (optional) → Chromaprint audio → FAISS index → DB update
- **Image:** PIL decode → pHash (single frame) → FAISS index → DB update (no audio, no DL, no Gemini)

---

### 3.3 Frontend (Web UI)

**Path:** `/home/vishnu/sports-media-protection/frontend/index.html`  
**Served at:** `http://localhost:8000/` and `http://localhost:8000/ui` by FastAPI  
**Tech:** Single-file SPA — Tailwind CSS + Chart.js + vanilla JS

#### Pages
| Tab | Features |
|---|---|
| Upload | Drag-and-drop or browse for video/image; SHA256 duplicate detection; watermark offer after upload |
| Library | Table of all assets with status/duration/size/watermark columns |
| Search | Upload video or image to find matches; results with similarity scores and verdicts |
| Monitor | Submit URLs for background monitoring; view jobs |
| Alerts | List of match alerts; review workflow |
| Stats | KPI dashboard with Chart.js; server system info |

#### Theme
- Dark navy (#060d1a) + orange accent (#f97316)
- Marble texture background
- Sidebar navigation

---

### 3.4 Desktop App

**Path:** `/home/vishnu/sports-media-protection/desktop-app/`  
**Start:** `cd desktop-app && python3 main.py`  
**Tech:** PySide6 6.11.0 + requests

#### Pages (13 Python files)
| Page | File | Features |
|---|---|---|
| Dashboard | `dashboard_page.py` | KPIs, server health, recent assets |
| Assets | `assets_page.py` | Upload video/image, list, delete, embed watermark |
| Search | `search_page.py` | Browse video/image → search → results table + Gemini AI panel |
| Watermark | `watermark_page.py` | Embed into asset; detect in video/image |
| Monitor | `monitor_page.py` | Submit URLs, view jobs |
| Reports | `reports_page.py` | View evidence reports |
| Settings | `settings_page.py` | Configure server URL |

#### App Identity
- Window title: **True Forge**
- Sidebar: **True Forge** / "Media Protection Platform"
- QSettings key: `TrueForge/DesktopApp`

---

### 3.5 Android App

**Path:** `/home/vishnu/sports-media-protection/android-app/`  
**Tech:** Kotlin, Jetpack Compose, MVVM, Room DB, Retrofit, Coroutines  
**Min SDK:** 26 | **Target SDK:** 35

#### Architecture
```
SmpApplication
└── AppContainer (singleton DI)
    ├── NetworkClient (Retrofit → FastAPI)
    ├── SmpDatabase (Room, local_assets table)
    ├── ConnectivityObserver
    └── Repositories:
        ├── AssetRepository
        ├── SearchRepository
        ├── WatermarkRepository
        ├── MonitorRepository
        └── StatsRepository
```

#### Screens (7, bottom nav + Settings via top bar)
| Screen | Online | Offline |
|---|---|---|
| Assets (Library) | Upload to server | Register locally (pHash + audio) |
| Search | Upload to server | Local pHash + audio fusion search |
| Watermark | Server embed/detect | DCT offline embed/detect |
| Monitor | Submit URL jobs | Shows OfflineNotice |
| Alerts | View/review alerts | Shows OfflineNotice |
| Stats | Server KPIs + device info | Shows OfflineNotice |
| Settings | Server URL config | Always available |

#### Offline Engines (`offline/` package)
| Engine | Algorithm | Notes |
|---|---|---|
| PHashEngine | 32×32 DCT perceptual hash, 63-bit | Operates on Bitmap (media-agnostic) |
| AudioFingerprintEngine | FFT spectral peak hashing, 32-byte | Video only — skipped for images |
| WatermarkEngine | DCT 8×8 block, COEFF[4][5], strength=12 | Operates on Bitmap (media-agnostic) |
| VideoFrameExtractor | MediaMetadataRetriever | Video only |
| LocalSearchEngine | 0.65×pHash + 0.35×audio fusion | Audio weight = 0 when no audio |
| DeviceCapabilities | OpenGL ES 3.1 detection | GPU/CPU routing label |

#### Image Support (new)
- Assets: expandable FAB → Video mini-FAB / Image mini-FAB
- Search: two side-by-side buttons (Video / Image)
- Watermark detect: two side-by-side buttons (Video / Image)
- Images skip frame extraction and audio — pHash computed directly from decoded bitmap
- `FileUtils.isImageUri()` + `FileUtils.loadBitmapFromUri()` handle the branching
- `LocalAsset.isImage()` extension detects type from filename extension for DB-stored assets

#### Local Database (Room)
**Table:** `local_assets`
| Column | Type | Notes |
|---|---|---|
| assetId | String PK | UUID |
| filename | String | Original filename |
| localPath | String | Content URI |
| status | String | pending/processing/ready/failed |
| durationSeconds | Float? | null for images |
| pHashFingerprints | String? | JSON array of hex Long strings |
| audioFingerprint | String? | hex byte array; null for images |
| createdAt | Long | epoch ms |
| syncedToServer | Boolean | false by default |
| serverAssetId | String? | if synced |
| watermarkEmbedded | Boolean | |
| watermarkedPath | String? | cache path to preview PNG |

---

### 3.6 Infrastructure

**Docker Compose** (`/home/vishnu/sports-media-protection/`):
```
make up       # docker compose up -d
make down     # docker compose down
make logs     # docker compose logs -f
make shell    # shell into backend container
make test     # run tests
```

**Services:**
- `postgres` — PostgreSQL 16, port 5432
- `backend` — FastAPI, port 8000

**Data directories:**
- `./data/originals/{asset_id}/` — original files + watermarked output
- `./data/frames/{asset_id}/` — extracted frames (temp, cleaned after fingerprinting)
- `./data/indices/` — FAISS index files

**Key env vars** (`.env`):
| Var | Default |
|---|---|
| MATCH_THRESHOLD | 0.85 |
| FRAME_SAMPLE_RATE | 1 |
| HASH_SIZE | 16 |
| GOOGLE_API_KEY | (optional, enables Gemini) |
| POSTGRES_USER/PASSWORD/DB | explicit in .env |
| ALLOWED_ORIGINS | configurable for CORS |

**Production:**
- `docker-compose.prod.yml` — nginx on port 80 + backend + postgres
- `nginx.conf` — reverse proxy

---

### 3.7 Upgrade Path (Tier 2 — not yet implemented)

| Current (Tier 1) | Upgrade |
|---|---|
| pHash | DINOv2 ViT-S/8 |
| FAISS flat | Qdrant |
| Sync processing | Redis + Celery |
| DCT watermark | VideoSeal (GPU neural watermarking) |
| No monitoring | YouTube Data API integration |

---

*Report generated: 2026-04-27*