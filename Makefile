.PHONY: up down logs test lint migrate fmt

up:
	docker compose up --build

down:
	docker compose down -v

logs:
	docker compose logs -f backend

migrate:
	docker compose exec backend alembic upgrade head

test:
	cd backend && python -m pytest -v --cov=app

lint:
	cd backend && ruff check . && mypy app

fmt:
	cd backend && ruff format .
