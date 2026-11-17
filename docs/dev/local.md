# Локальная разработка

Два способа: всё в Docker одной командой (быстро посмотреть и проверить интеграцию) или сервисы на своём
компьютере (удобнее отлаживать). Модели в обоих случаях — демо-реализации внутри API, GPU не нужен.

## Что установить

| Инструмент | Версия | Для чего |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) | 0.11+ | Python 3.13 и зависимости сервера, сервисов и ML |
| PostgreSQL + pgvector | 16+ / 0.8+ | БД (или контейнер `pgvector/pgvector:0.8.7-pg17-bookworm`) |
| Node.js | 22 | панель администратора |
| Flutter | 3.50 (stable) | клиенты |
| ffmpeg | любая | разбор и кодирование звука |
| Docker с Compose | 25+ / 2.24+ | стенд целиком |

## Вариант 1. Стенд в Docker

```bash
make dev-up            # = docker compose --env-file infra/compose/dev.env -f infra/compose/compose.yaml -f infra/compose/compose.dev.yaml up -d --build
make dev-superadmin    # создаст суперадминистратора и напечатает ссылку otpauth:// для 2FA
```

- API и приложения: `http://localhost:8080` (в клиенте — «Адрес сервера» на экране приветствия);
- панель администратора: `http://localhost:8080/admin/`;
- PostgreSQL: `localhost:15432` (пользователь `doomich`, пароль из `infra/compose/dev.env`).

Ссылку `otpauth://` добавьте в приложение-аутентификатор (или прочитайте код: `python -c "import pyotp; print(pyotp.TOTP(pyotp.parse_uri('<ссылка>').secret).now())"`).

Демо-вуз с группой, расписанием на две недели и кодами приглашения:

```bash
docker compose --env-file infra/compose/dev.env -f infra/compose/compose.yaml -f infra/compose/compose.dev.yaml exec api doomich-api seed-demo
```

Сервисы речи и навигации на стенде выключены (API отвечает демо-движками). Включить — профилями перед командой:
`docker compose --env-file infra/compose/dev.env -f infra/compose/compose.yaml -f infra/compose/compose.dev.yaml --profile speech --profile nav up -d`.

## Вариант 2. Сервисы на своём компьютере

```bash
uv sync --all-packages                 # один .venv на все Python-пакеты
# роль приложения — не суперпользователь: на суперпользователя построчная защита (RLS) не действует
sudo -u postgres psql -c "CREATE ROLE doomich LOGIN PASSWORD 'doomich'" -c "CREATE DATABASE doomich OWNER doomich"
sudo -u postgres psql -d doomich -c "CREATE EXTENSION vector"
```

Переменные окружения (полный список — `services/api/src/doomich_api/config.py`):

```bash
export DOOMICH_ENV=dev
export DOOMICH_DATABASE_URL=postgresql+asyncpg://doomich:doomich@localhost:5432/doomich
export DOOMICH_LLM_PROVIDER=fake DOOMICH_EMBEDDINGS_PROVIDER=fake DOOMICH_RERANKER_PROVIDER=fake
export DOOMICH_ASR_PROVIDER=fake DOOMICH_TTS_PROVIDER=fake
export DOOMICH_RUN_TASKS_INLINE=true   # фоновые задачи сразу в процессе API, без Celery
```

```bash
uv run doomich-api migrate
uv run doomich-api seed-demo
uv run uvicorn doomich_api.main:app --reload --port 8000     # из каталога services/api
```

С настоящими моделями: поднимите vLLM (см. [развёртывание](deploy.md#модели)) и задайте
`DOOMICH_LLM_PROVIDER=openai`, `DOOMICH_LLM_BASE_URL=http://<gpu>:8001/v1` и т. д. В команде разработчики
обычно пользуются общим GPU-сервером по VPN.

Панель администратора (запросы `/admin/v1` проксируются на API):

```bash
cd apps/admin && npm ci && DOOMICH_API=http://localhost:8000 npm run dev   # http://localhost:5173/admin/
```

Клиенты:

```bash
cd apps/client && flutter pub get
cd desktop && flutter run -d linux --dart-define=DOOMICH_API=http://localhost:8000
cd mobile && flutter run --dart-define=DOOMICH_API=http://10.0.2.2:8000          # эмулятор Android
```

## Тесты и проверки

```bash
make lint
make test-api TEST_PG=postgresql://postgres:<пароль>@localhost:5432   # создаёт временную БД и роль сам
make test-services test-ml test-admin test-client
```

Сквозной тест клиента против живого сервера (регистрация, чат с инструментом расписания, документ
со ссылкой на источник, озвучка и голосовой канал):

```bash
cd apps/client/packages/doomich_core
DOOMICH_E2E_API=http://localhost:8080 DOOMICH_E2E_INVITE=<код из seed-demo> dart test --run-skipped -t e2e test/e2e_test.dart
```

Всё это же выполняет CI (`.github/workflows/ci.yml`): тесты Python с PostgreSQL, панель, клиенты,
сборки APK, Linux и Windows, образы Docker и сквозной тест на стенде из compose.

## Полезно знать

- **Миграции** лежат в `services/api/src/doomich_api/migrations` (внутри пакета, чтобы работать из образа).
  Новая миграция: `cd services/api && uv run alembic revision --autogenerate -m "..."`.
- **Изоляция данных.** Таблицы с данными пользователей и вузов защищены RLS. Если запрос «ничего не
  находит», проверьте, что он идёт через `user_session`/`session_scope` с правильным контекстом.
- **Секреты.** В `DOOMICH_ENV=prod` API не стартует с секретами из примеров — это нормально.
- **Локализация клиентов** — `apps/client/packages/doomich_ui/lib/l10n/app_ru.arb` (шаблон) и `app_en.arb`;
  после правки: `flutter gen-l10n` в `packages/doomich_ui`.
