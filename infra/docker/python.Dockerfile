# syntax=docker/dockerfile:1.10
# Общий образ Python-сервисов «Думыча»: api (и воркеры Celery), asr, tts, nav.
#
#   docker build -f infra/docker/python.Dockerfile --build-arg PACKAGE=doomich-api -t doomich/api .
#   docker build -f infra/docker/python.Dockerfile --build-arg PACKAGE=doomich-asr \
#       --build-arg EXTRAS="--extra gigaam --extra whisper" \
#       --build-arg BASE_IMAGE=nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04 -t doomich/asr .
#
# Python ставится через uv в /opt/python, поэтому базой может быть и Ubuntu, и образ CUDA без Python.
#
# Если сеть вуза подменяет TLS-сертификаты (прокси с проверкой трафика), передайте полный набор корневых
# сертификатов вместе с корпоративным: docker build --secret id=ca_bundle,src=/путь/ca-bundle.crt ...

# Ubuntu 24.04 — как и образы CUDA для GPU-варианта: одинаковые системные пакеты на CPU и GPU
ARG BASE_IMAGE=ubuntu:24.04
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.11

FROM ${UV_IMAGE} AS uv

FROM ${BASE_IMAGE} AS build
COPY --from=uv /uv /usr/local/bin/uv
ARG PYTHON_VERSION=3.13
ENV UV_PYTHON_INSTALL_DIR=/opt/python \
    UV_PYTHON_PREFERENCE=only-managed \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
RUN --mount=type=cache,target=/root/.cache/uv --mount=type=secret,id=ca_bundle,required=false \
    if [ -s /run/secrets/ca_bundle ]; then export SSL_CERT_FILE=/run/secrets/ca_bundle; fi; \
    uv python install ${PYTHON_VERSION}
WORKDIR /src

# сначала только описания пакетов: слой с зависимостями пересобирается, только когда они меняются
COPY pyproject.toml uv.lock ./
COPY libs/common/pyproject.toml libs/common/pyproject.toml
COPY services/api/pyproject.toml services/api/pyproject.toml
COPY services/asr/pyproject.toml services/asr/pyproject.toml
COPY services/tts/pyproject.toml services/tts/pyproject.toml
COPY services/nav/pyproject.toml services/nav/pyproject.toml
COPY ml/pyproject.toml ml/pyproject.toml
ARG PACKAGE
ARG EXTRAS=""
RUN --mount=type=cache,target=/root/.cache/uv --mount=type=secret,id=ca_bundle,required=false \
    if [ -s /run/secrets/ca_bundle ]; then export SSL_CERT_FILE=/run/secrets/ca_bundle; fi; \
    uv sync --frozen --no-dev --no-install-workspace --package "${PACKAGE}" ${EXTRAS}

COPY libs libs
COPY services services
RUN --mount=type=cache,target=/root/.cache/uv --mount=type=secret,id=ca_bundle,required=false \
    if [ -s /run/secrets/ca_bundle ]; then export SSL_CERT_FILE=/run/secrets/ca_bundle; fi; \
    uv sync --frozen --no-dev --no-editable --package "${PACKAGE}" ${EXTRAS}

FROM ${BASE_IMAGE}
# ffmpeg — разбор и кодирование звука (api, asr, tts); для nav можно передать пустой список
ARG APT_PACKAGES="ffmpeg"
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates tini ${APT_PACKAGES} \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 doomich \
    && useradd --system --uid 10001 --gid doomich --home-dir /app --shell /usr/sbin/nologin doomich \
    # точки монтирования томов принадлежат doomich: новый именованный том наследует владельца
    && mkdir -p /data/storage /registry /models \
    && chown -R doomich:doomich /data /registry /models
COPY --from=build /opt/python /opt/python
COPY --from=build --chown=doomich:doomich /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
USER doomich
ENTRYPOINT ["/usr/bin/tini", "--"]
