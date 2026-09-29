# POSIX make targets. Windows (PowerShell) equivalents: scripts/*.ps1 — see README.
.PHONY: install dev api web test test-api test-web lint format migrate seed db-up db-down

install:
	uv sync --all-packages
	cd apps/web && npm install

db-up:
	docker compose up -d --wait postgres

db-down:
	docker compose down

migrate:
	cd apps/api && uv run alembic upgrade head

seed:
	cd apps/api && uv run python -m app.seed

api:
	cd apps/api && uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

web:
	cd apps/web && npm run dev

# api + web concurrently; Ctrl+C stops both.
dev:
	@trap 'kill 0' INT TERM EXIT; \
	$(MAKE) --no-print-directory api & \
	$(MAKE) --no-print-directory web & \
	wait

test: test-api test-web

test-api:
	uv run pytest

test-web:
	cd apps/web && npm test

lint:
	uv run ruff check .
	uv run ruff format --check .
	cd apps/web && npm run lint

format:
	uv run ruff check --fix .
	uv run ruff format .
