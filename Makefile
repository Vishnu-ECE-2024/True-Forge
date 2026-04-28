.PHONY: help setup up down logs shell test clean reset

help:
	@echo "Sports Media Protection — Makefile"
	@echo ""
	@echo "  make setup    — Copy .env.example, create data dirs"
	@echo "  make up       — Start all services (build if needed)"
	@echo "  make down     — Stop all services"
	@echo "  make logs     — Tail all logs"
	@echo "  make shell    — Open bash in backend container"
	@echo "  make test     — Run backend tests"
	@echo "  make clean    — Remove containers and volumes"
	@echo "  make reset    — Wipe all data (DESTRUCTIVE)"

setup:
	@if [ ! -f .env ]; then cp .env.example .env; echo "Created .env — edit passwords before running"; fi
	@mkdir -p data/originals data/frames data/indices
	@echo "Setup complete. Run: make up"

up:
	docker compose up --build -d
	@echo "Backend: http://localhost:8000"
	@echo "API docs: http://localhost:8000/docs"
	@echo "Frontend: http://localhost:8000/ui"

down:
	docker compose down

logs:
	docker compose logs -f

shell:
	docker compose exec backend bash

test:
	docker compose exec backend pytest tests/ -v

clean:
	docker compose down --volumes --remove-orphans
	docker image rm sports-media-protection-backend 2>/dev/null || true

reset: clean
	rm -rf data/originals/* data/frames/* data/indices/*
	@echo "All data wiped."
