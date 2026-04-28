#!/bin/bash
# Sports Media Protection — Quick Launch Guide
# Run commands from the sports-media-protection root directory

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_URL="http://localhost:8000"
FRONTEND_URL="http://localhost:8000/ui"

echo "🎬 Sports Media Protection — Launcher"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Helper: check if Docker is running
check_docker() {
    if ! docker info > /dev/null 2>&1; then
        echo "❌ Docker is not running. Start Docker and try again."
        exit 1
    fi
}

# Helper: check if port is in use
check_port() {
    local port=$1
    if timeout 1 bash -c "echo >/dev/tcp/127.0.0.1/$port" 2>/dev/null; then
        return 0  # port is in use
    else
        return 1  # port is free
    fi
}

# Helper: wait for service
wait_for_service() {
    local url=$1
    local max_attempts=30
    local attempt=0

    echo "⏳ Waiting for service at $url..."
    while [ $attempt -lt $max_attempts ]; do
        if curl -s "$url/health" > /dev/null 2>&1; then
            echo "✅ Service ready!"
            return 0
        fi
        attempt=$((attempt + 1))
        sleep 1
    done

    echo "⚠️  Service took longer than expected. Check logs: make logs"
    return 1
}

# ─────────────────────────────────────────────────────────────
# START BACKEND & DATABASE
# ─────────────────────────────────────────────────────────────

start_backend() {
    echo ""
    echo "📦 Starting Backend (FastAPI + PostgreSQL)..."

    check_docker

    if check_port 8000; then
        echo "⚠️  Port 8000 already in use. Skip backend startup? (y/n)"
        read -r response
        if [[ ! "$response" =~ ^[Yy]$ ]]; then
            echo "Starting anyway..."
        else
            echo "Skipped."
            return 0
        fi
    fi

    cd "$PROJECT_ROOT"
    docker compose up -d
    wait_for_service "$BACKEND_URL"

    echo "✅ Backend running at $BACKEND_URL"
    echo "📊 Swagger docs: $BACKEND_URL/docs"
}

# ─────────────────────────────────────────────────────────────
# OPEN FRONTEND (Web UI)
# ─────────────────────────────────────────────────────────────

open_frontend() {
    echo ""
    echo "🌐 Opening Frontend (SPA)..."

    if ! check_port 8000; then
        echo "⚠️  Backend is not running. Start it first with: ./QUICKSTART.sh backend"
        return 1
    fi

    if command -v xdg-open > /dev/null; then
        xdg-open "$FRONTEND_URL"
    elif command -v open > /dev/null; then
        open "$FRONTEND_URL"
    else
        echo "📱 Open in browser: $FRONTEND_URL"
    fi

    echo "✅ Frontend opened at $FRONTEND_URL"
}

# ─────────────────────────────────────────────────────────────
# LAUNCH DESKTOP APP
# ─────────────────────────────────────────────────────────────

launch_desktop() {
    echo ""
    echo "🖥️  Launching Desktop App (PySide6)..."

    cd "$PROJECT_ROOT/desktop-app"

    if [ ! -d "venv" ]; then
        echo "📦 Creating virtual environment..."
        python3 -m venv venv
    fi

    source venv/bin/activate
    pip install -q -r requirements.txt

    echo "🚀 Starting desktop app..."
    python3 main.py &
    DESKTOP_PID=$!

    echo "✅ Desktop app started (PID: $DESKTOP_PID)"
    echo "💡 Set SERVER_URL env var before launch to change backend: export SERVER_URL=http://your-server:8000"
}

# ─────────────────────────────────────────────────────────────
# BUILD & RUN ANDROID APP
# ─────────────────────────────────────────────────────────────

build_android() {
    echo ""
    echo "📱 Building Android App..."

    cd "$PROJECT_ROOT/android-app"

    if ! command -v gradlew > /dev/null; then
        echo "❌ Gradle wrapper not found. Make sure you're in android-app directory."
        return 1
    fi

    echo "🔨 Building APK (debug)..."
    ./gradlew assembleDebug

    APK_PATH="app/build/outputs/apk/debug/app-debug.apk"
    if [ -f "$APK_PATH" ]; then
        echo "✅ APK built: $APK_PATH"
        echo "💡 Install on emulator/device: adb install -r $APK_PATH"
    fi
}

run_android() {
    echo ""
    echo "📱 Running Android App (on connected device/emulator)..."

    cd "$PROJECT_ROOT/android-app"

    echo "🚀 Installing and launching..."
    ./gradlew installDebug
    ./gradlew runDebug

    echo "✅ App launched on device"
}

# ─────────────────────────────────────────────────────────────
# LOGS & MONITORING
# ─────────────────────────────────────────────────────────────

show_logs() {
    echo ""
    echo "📋 Backend Logs:"
    cd "$PROJECT_ROOT"
    docker compose logs -f backend
}

show_status() {
    echo ""
    echo "📊 Service Status:"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    if check_port 8000; then
        echo "✅ Backend: Running (http://localhost:8000)"
        echo "   Health: $(curl -s http://localhost:8000/health || echo 'unreachable')"
    else
        echo "❌ Backend: Not running"
    fi

    if check_port 5432; then
        echo "✅ PostgreSQL: Running (localhost:5432)"
    else
        echo "❌ PostgreSQL: Not running"
    fi

    echo ""
    echo "URLs:"
    echo "  🌐 Frontend:  $FRONTEND_URL"
    echo "  📊 API Docs: $BACKEND_URL/docs"
    echo "  🏥 Health:   $BACKEND_URL/health"
}

# ─────────────────────────────────────────────────────────────
# MAIN MENU
# ─────────────────────────────────────────────────────────────

show_menu() {
    echo ""
    echo "Commands:"
    echo "  ./QUICKSTART.sh backend          Start backend + database"
    echo "  ./QUICKSTART.sh frontend         Open web UI in browser"
    echo "  ./QUICKSTART.sh desktop          Launch desktop app"
    echo "  ./QUICKSTART.sh android-build    Build Android APK"
    echo "  ./QUICKSTART.sh android-run      Build & run on device/emulator"
    echo "  ./QUICKSTART.sh all              Start all components"
    echo "  ./QUICKSTART.sh status           Show service status"
    echo "  ./QUICKSTART.sh logs             Show backend logs (live)"
    echo "  ./QUICKSTART.sh stop             Stop backend & database"
    echo ""
}

stop_backend() {
    echo ""
    echo "🛑 Stopping Backend & Database..."
    cd "$PROJECT_ROOT"
    docker compose down
    echo "✅ Stopped"
}

# ─────────────────────────────────────────────────────────────
# COMMAND ROUTING
# ─────────────────────────────────────────────────────────────

case "${1:-help}" in
    backend)
        start_backend
        ;;
    frontend)
        start_backend
        sleep 2
        open_frontend
        ;;
    desktop)
        launch_desktop
        ;;
    android-build)
        build_android
        ;;
    android-run)
        run_android
        ;;
    all)
        start_backend
        sleep 2
        open_frontend
        sleep 1
        echo ""
        echo "⚠️  Desktop app and Android require manual launch."
        echo "   Desktop: ./QUICKSTART.sh desktop"
        echo "   Android: ./QUICKSTART.sh android-run"
        ;;
    status)
        show_status
        ;;
    logs)
        show_logs
        ;;
    stop)
        stop_backend
        ;;
    help|--help|-h)
        show_menu
        ;;
    *)
        echo "❌ Unknown command: $1"
        show_menu
        exit 1
        ;;
esac
