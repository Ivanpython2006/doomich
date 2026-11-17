# Развёртывание и эксплуатация

Конфигурации серверов и бюджет — в [требованиях к серверу](../06-server-requirements.md). Ниже — как
поставить «Думыч» на подготовленный сервер с Ubuntu 24.04 и одной или двумя видеокартами NVIDIA.

## 1. Подготовка сервера (Ansible)

```bash
cd infra/ansible
cp inventory.example.ini inventory.ini                  # адреса серверов
ansible-vault create group_vars/all/vault.yml           # секреты, см. ниже
ansible-playbook -i inventory.ini site.yml --ask-vault-pass
```

Плейбук ставит Docker и межсетевой экран (наружу — только 80/443, SSH — из сети администраторов),
драйвер NVIDIA и nvidia-container-toolkit, забирает код, формирует `infra/compose/.env` из vault,
собирает образы, запускает сервис и включает ежедневные резервные копии.

Секреты для `vault.yml` удобно получить скриптом:

```bash
infra/scripts/gen-secrets.sh
# POSTGRES_PASSWORD → vault_postgres_password, DOOMICH_DB_PASSWORD → vault_db_password,
# DOOMICH_JWT_SECRET → vault_jwt_secret, DOOMICH_MASTER_KEY → vault_master_key,
# DOOMICH_INVITE_PEPPER → vault_invite_pepper, GRAFANA_ADMIN_PASSWORD → vault_grafana_password
```

**Мастер-ключ** шифрует ключи пользователей: без него переписку и файлы не расшифровать. Храните его
копию отдельно от сервера и резервных копий (сейф, менеджер паролей вуза). Менять мастер-ключ на
работающей установке нельзя без перешифрования ключей пользователей.

## 2. Ручной запуск (без Ansible)

```bash
cp infra/compose/.env.example infra/compose/.env
infra/scripts/gen-secrets.sh >> infra/compose/.env         # и удалите пустые строки секретов выше
# поправьте адрес, имя сервера и модели в .env
mkdir -p infra/compose/certs                                # fullchain.pem и privkey.pem
docker compose -f infra/compose/compose.yaml -f infra/compose/compose.gpu.yaml up -d --build
docker compose -f infra/compose/compose.yaml exec api doomich-api create-superadmin --login root
```

Состав сервисов: `postgres`, `valkey` (очередь задач), `migrate` (миграции при каждом запуске), `api`,
`worker` (документы, расписания), `worker-heavy` (конспекты лекций), `beat` (расписание задач), `asr`,
`tts`, `nav`, `nginx`, а на GPU-узле — `vllm-llm`, `vllm-embed`, `vllm-rerank`.

### HTTPS

nginx ждёт сертификат в `infra/compose/certs/` (`fullchain.pem`, `privkey.pem`). Подойдёт сертификат
вуза или Let's Encrypt: проверочный путь `/.well-known/acme-challenge/` отдаётся из тома `acme`.
Первый сертификат можно получить до запуска nginx: `certbot certonly --standalone -d doomich.example.ru`,
затем скопировать файлы и настроить продление с `--deploy-hook "docker compose ... restart nginx"`.

### Панель администратора — только из VPN

`/admin/` и `/admin/v1/` закрыты для всех, кроме адресов из `admin-allow.conf`. Укажите подсеть VPN:

```nginx
allow 10.8.0.0/24;
deny all;
```

(в `infra/compose/admin-allow.conf` и `DOOMICH_ADMIN_ALLOW_FILE=./admin-allow.conf` в `.env` — Ansible
делает это сам из `doomich_admin_networks`). Подсети Docker не добавляйте.

## Модели

Модели скачиваются с Hugging Face при первом запуске vLLM в том `models` (нужен доступ к huggingface.co
или зеркалу; для закрытых моделей — `HF_TOKEN`). Выбор под видеокарту — в `.env`:

| Параметр | Конфигурация А (1× 24 ГБ) | Конфигурация Б (2× 24 ГБ) |
|---|---|---|
| `LLM_MODEL_ID` | модель до ~9B в FP8 | Qwen3.6-35B-A3B в 4 бит (AWQ/GPTQ) |
| `LLM_GPU` / `SPEECH_GPU` | 0 / 0 | 0 / 1 |
| `LLM_GPU_MEMORY` | 0.6 (место для речи и эмбеддингов на той же карте) | 0.88 |

API обращается к моделям по именам `doomich-llm`, `doomich-embed`, `doomich-rerank` — их задаёт compose,
поэтому смена модели — это смена `LLM_MODEL_ID` и перезапуск `vllm-llm`. После смены модели эмбеддингов
документы нужно переиндексировать (размерность — `DOOMICH_EMBEDDING_DIM` в `app.env`).

LoRA-адаптеры вузов vLLM подключает на лету из реестра (`VLLM_ALLOW_RUNTIME_LORA_UPDATING`), без
перезапуска: достаточно активировать версию в панели администратора.

### Модели речи

Без `infra/compose/speech.env` сервисы речи работают демо-движками. Для настоящих моделей скопируйте
`speech.env.example` и положите модели в том `models`:

```bash
docker compose -f infra/compose/compose.yaml run --rm --entrypoint sh asr -c \
  'cd /models && python - <<EOF
from huggingface_hub import snapshot_download
snapshot_download("<репозиторий GigaAM-v3 в формате sherpa-onnx>", local_dir="/models/gigaam-v3-ctc")
EOF'
```

Whisper (faster-whisper) скачивает модель сам при первом запросе. Голоса синтеза выбираются по итогам
бенчмарка (см. [архитектуру](../05-architecture-and-stack.md)), модели sherpa-onnx кладутся в `/models/tts-*`.
GigaAM через sherpa-onnx по умолчанию работает на CPU; на GPU — движок `hf_ctc` с `"device": "cuda"`.

## Резервные копии и восстановление

`infra/scripts/backup.sh` (Ansible запускает его каждую ночь) сохраняет дамп БД, файлы пользователей и
реестр моделей в `BACKUP_DIR` и удаляет копии старше `KEEP_DAYS`. Отправку в другой ЦОД настройте
отдельно, например `restic` или `rsync` по расписанию.

Восстановление на чистом сервере:

```bash
docker compose -f infra/compose/compose.yaml up -d postgres
docker compose -f infra/compose/compose.yaml exec -T postgres pg_restore -U postgres -d doomich --clean --if-exists < db-<дата>.dump
for v in storage registry; do
  docker run --rm -v doomich_$v:/dst -v "$PWD":/src alpine:3 tar -xzf /src/$v-<дата>.tar.gz -C /dst
done
docker compose -f infra/compose/compose.yaml -f infra/compose/compose.gpu.yaml up -d
```

`.env` с тем же мастер-ключом обязателен — иначе данные пользователей не расшифруются.

## Мониторинг

```bash
docker compose -f infra/compose/compose.yaml -f infra/compose/compose.gpu.yaml \
  -f infra/compose/compose.monitoring.yaml --profile gpu up -d
```

Grafana — `127.0.0.1:3000` на сервере (через VPN или `ssh -L 3000:127.0.0.1:3000`), панель «Думыч — обзор»:
запросы и задержки API, ошибки, очередь и время до первого токена LLM, загрузка и память GPU.
Правила оповещений — `infra/monitoring/alerts.yml` (API или LLM недоступны, 5% ошибок, медленные ответы,
очередь к LLM, память GPU, диск). Канал доставки (почта, Telegram) подключите в Alertmanager или Grafana.

Журналы: `docker compose ... logs -f api worker`. IP-адреса и тексты запросов в журналы не пишутся.

## Обновление

```bash
git pull
docker compose -f infra/compose/compose.yaml -f infra/compose/compose.gpu.yaml up -d --build
```

Миграции применяются автоматически перед запуском API. Перед обновлением сделайте резервную копию.

## Безопасность — чек-лист

- `DOOMICH_ENV=prod`: API не стартует с секретами из примеров.
- Панель администратора — только из VPN; администраторы входят с паролем и 2FA, отключение действует сразу.
- Источники расписания не могут обращаться во внутреннюю сеть, кроме хостов из
  `DOOMICH_SCHEDULE_SOURCE_PRIVATE_HOSTS`.
- Порты PostgreSQL, Valkey, vLLM и сервисов речи наружу не публикуются; Grafana — только на 127.0.0.1.
- Метрики и документация API через nginx не отдаются.
