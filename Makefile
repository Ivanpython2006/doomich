# Частые команды разработки «Думыча». Подробности — docs/dev/local.md.
COMPOSE_DEV = docker compose --env-file infra/compose/dev.env -f infra/compose/compose.yaml -f infra/compose/compose.dev.yaml
TEST_PG ?= postgresql://postgres:postgres@localhost:5432

.PHONY: help setup lint test test-api test-services test-ml test-admin test-client dev-up dev-down dev-logs dev-superadmin images

help:
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-16s %s\n", $$1, $$2}'

setup: ## Установить зависимости: Python (uv), панель, клиенты Flutter
	uv sync --all-packages
	cd apps/admin && npm ci
	cd apps/client && flutter pub get

lint: ## Проверки стиля и типов
	uv run ruff check . && uv run ruff format --check .
	cd apps/admin && npm run typecheck && npm run lint
	cd apps/client && flutter analyze

test: test-api test-services test-ml test-admin test-client ## Все тесты

test-api: ## Тесты API (нужен PostgreSQL с pgvector: TEST_PG=postgresql://...)
	cd services/api && DOOMICH_TEST_PG=$(TEST_PG) uv run pytest -q

test-services: ## Тесты сервисов речи и навигации
	cd services/asr && uv run pytest -q
	cd services/tts && uv run pytest -q
	cd services/nav && uv run pytest -q

test-ml: ## Тесты ML-платформы
	cd ml && uv run pytest -q

test-admin: ## Тесты панели администратора
	cd apps/admin && npm test

test-client: ## Тесты клиентов Flutter
	cd apps/client/packages/doomich_core && dart test
	cd apps/client/packages/doomich_ui && flutter test
	cd apps/client/mobile && flutter test
	cd apps/client/desktop && flutter test

dev-up: ## Поднять стенд разработки (API, воркеры, БД, nginx и панель на :8080)
	$(COMPOSE_DEV) up -d --build

dev-down: ## Остановить стенд разработки
	$(COMPOSE_DEV) down

dev-logs: ## Журналы стенда
	$(COMPOSE_DEV) logs -f --tail=100

dev-superadmin: ## Создать суперадминистратора на стенде (LOGIN=root)
	$(COMPOSE_DEV) exec api doomich-api create-superadmin --login $(or $(LOGIN),root)

images: ## Собрать боевые образы
	docker compose -f infra/compose/compose.yaml -f infra/compose/compose.gpu.yaml build
