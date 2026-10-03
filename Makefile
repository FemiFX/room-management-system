.PHONY: up down logs migrate seed-user seed-demo test dev-up dev-down dev-logs dev-seed

up:
	docker compose up --build -d

down:
	docker compose down -v

logs:
	docker compose logs -f api worker scheduler

migrate:
	docker compose run --rm api alembic upgrade head

seed-user:
	docker compose run --rm api python -m app.cli seed-super-admin --email admin@example.com --display-name "Initial Admin"

seed-demo:
	docker compose run --rm api python scripts/seed_demo_data.py --reset

test:
	pytest

# ─── Local development ────────────────────────────────────────────────
# Uses .env.dev instead of .env, so a laptop stack cannot reach a real
# system. See docker-compose.dev.yml for why that matters.
DEV := -f docker-compose.yml -f docker-compose.dev.yml

dev-up:
	docker compose $(DEV) up --build -d

dev-down:
	docker compose $(DEV) down -v

dev-logs:
	docker compose $(DEV) logs -f api worker scheduler

dev-seed:
	docker compose $(DEV) run --rm api python scripts/seed_demo_data.py --reset
