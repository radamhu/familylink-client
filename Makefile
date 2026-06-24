.PHONY: install test test-unit test-server lint lint-fix format typecheck \
        dev migrate pre-commit clean \
        refresh-cookies \
        docker-build docker-up docker-deploy docker-down docker-restart docker-logs docker-clean docker-purge

# ── Local ─────────────────────────────────────────────────────────────────────

install:
	python -m venv .venv --prompt familylink-client
	.venv/bin/pip install -e ".[dev,test,server]"
	.venv/bin/pre-commit install

test:
	python -m pytest

test-unit:
	python -m pytest tests/unit/

test-server:
	python -m pytest tests/server/

lint:
	ruff check src tests

lint-fix:
	ruff check --fix src tests

format:
	ruff format src tests

typecheck:
	mypy src

dev:
	uvicorn familylink_server.main:app --reload

migrate:
	alembic upgrade head

pre-commit:
	pre-commit install

clean:
	rm -rf .venv
	rm -rf .mypy_cache .pytest_cache
	rm -rf src/*.egg-info

# ── Docker ─────────────────────────────────────────────────────────────────────

refresh-cookies:
	familylink export-cookies --browser chrome --base64

docker-build: refresh-cookies
	docker compose build web

docker-up:
	docker compose up -d

docker-deploy: refresh-cookies
	docker compose up --build -d web

docker-down:
	docker compose down

docker-restart: refresh-cookies
	docker compose up --build -d web

docker-logs:
	docker compose logs -f

docker-clean:
	docker compose down --remove-orphans -v

docker-purge:
	docker compose down --remove-orphans -v
	docker system prune -af --volumes
