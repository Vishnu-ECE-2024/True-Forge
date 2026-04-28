# Sports Media Protection — Quick Launch Commands

All commands run from the root directory: `/home/vishnu/sports-media-protection/`

## 🚀 Quick Start (One Command)

```bash
./QUICKSTART.sh all
```

This starts the backend and opens the frontend in your browser. Then:
- **Desktop app:** `./QUICKSTART.sh desktop`
- **Android:** `./QUICKSTART.sh android-run`

---

## 📦 Backend & Database

| Task | Command |
|------|---------|
| **Start** | `./QUICKSTART.sh backend` or `docker compose up -d` |
| **Stop** | `./QUICKSTART.sh stop` or `docker compose down` |
| **Logs** | `./QUICKSTART.sh logs` or `docker compose logs -f backend` |
| **Status** | `./QUICKSTART.sh status` |
| **Shell** | `docker compose exec backend bash` |
| **DB shell** | `docker compose exec postgres psql -U postgres smp` |

**Backend URL:** `http://localhost:8000`
**API Docs:** `http://localhost:8000/docs`
**Health check:** `curl http://localhost:8000/health`

---

## 🌐 Frontend (Web UI)

| Task | Command |
|------|---------|
| **Open** | `./QUICKSTART.sh frontend` |
| **Manual** | `http://localhost:8000/ui` |

The SPA is served by FastAPI. No separate dev server needed.

**Features:** Upload assets, search, watermark, monitor, alerts, dashboard, settings.

---

## 🖥️ Desktop App (PySide6)

| Task | Command |
|------|---------|
| **Launch** | `./QUICKSTART.sh desktop` |
| **Manual** | `cd desktop-app && python3 main.py` |
| **Reinstall deps** | `cd desktop-app && pip install -r requirements.txt` |

**Settings:**
- Change backend: `export SERVER_URL=http://your-server:8000` (before launch)
- Default: `http://localhost:8000`

**Features:** 7 pages (Dashboard, Assets, Search, Watermark, Monitor, Reports, Settings)

---

## 📱 Android App

### Build

```bash
./QUICKSTART.sh android-build
```

Or manually:
```bash
cd android-app
./gradlew assembleDebug
# Output: app/build/outputs/apk/debug/app-debug.apk
```

### Install & Run

```bash
./QUICKSTART.sh android-run
```

Or manually:
```bash
cd android-app
./gradlew installDebug runDebug
```

**Connected device check:**
```bash
adb devices
```

**Manual install:**
```bash
adb install -r android-app/app/build/outputs/apk/debug/app-debug.apk
```

**Features:** 7 screens (Assets, Search, Watermark, Monitor, Alerts, Stats, Settings)
- Offline: pHash fingerprinting, audio FFT, DCT watermark
- Online: server search, watermark embed/detect
- Auto-routing: uses offline engines when no internet

---

## 🔧 Configuration

### Backend Environment Variables
Edit `.env` in root directory:
```
POSTGRES_USER=postgres
POSTGRES_PASSWORD=smp_dev
POSTGRES_DB=smp
MATCH_THRESHOLD=0.85
FRAME_SAMPLE_RATE=1
HASH_SIZE=16
GOOGLE_API_KEY=your-key-here
```

### Android
- **Server URL config:** Settings screen in app
- **Offline engines:** Auto-detected (no config needed)
- **GPU detection:** Automatic (shows in Settings)

### Desktop
- **Server URL:** Settings page
- **Auto-detect:** Dark theme + current backend

---

## 📊 Useful Commands

```bash
# Check what's running
lsof -i :8000          # Backend
lsof -i :5432          # Database

# Rebuild everything
docker compose down -v && docker compose up -d

# Android development
cd android-app
./gradlew assembleDebug    # Build only
./gradlew installDebug     # Install only
./gradlew runDebug         # Run only

# Database management
docker compose exec postgres psql -U postgres smp
# Then: SELECT * FROM assets;  (list all videos)
```

---

## ✅ Troubleshooting

| Issue | Solution |
|-------|----------|
| Backend won't start | `docker compose logs backend` → check GOOGLE_API_KEY |
| Port 8000 in use | `lsof -i :8000` → kill process or use different port |
| Database errors | `docker compose down -v && docker compose up -d` (fresh start) |
| Desktop app can't connect | Check `SERVER_URL` env var, ensure backend is running |
| Android won't install | `adb devices` → check device is connected; `adb logcat` for errors |

---

## 📚 Stack

| Component | Tech | Port |
|-----------|------|------|
| Backend | FastAPI (Python) | 8000 |
| Database | PostgreSQL 16 | 5432 |
| Frontend | SPA (HTML/JS) | 8000 |
| Desktop | PySide6 (Python) | — |
| Android | Kotlin MVVM | — |
| Search | FAISS (CPU) | — |
| Watermark | DCT (CPU) | — |
| Fingerprint | pHash + FFT | — |
