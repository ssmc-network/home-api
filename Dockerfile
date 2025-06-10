ARG PYTHON_VERSION=3.13.4

FROM python:${PYTHON_VERSION}-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1
WORKDIR /usr/src/app
ENV PATH=/root/.local/bin:$PATH

RUN --mount=type=cache,target=/var/lib/apt,sharing=locked \
    --mount=type=cache,target=/var/cache/apt,sharing=locked \
    apt-get update && apt-get -y dist-upgrade

RUN --mount=type=cache,target=/var/lib/apt,sharing=locked \
    --mount=type=cache,target=/var/cache/apt,sharing=locked \
    apt-get update && apt-get -y install --no-install-recommends \
    ffmpeg

# 依存解決 (本番用: 通常依存 only)
FROM base AS prod-deps
COPY --from=goegoe0212/poetry-image:latest /root/.local /root/.local
RUN poetry config virtualenvs.create false

COPY ./app/pyproject.toml ./app/poetry.lock /usr/src/app/
RUN poetry install --without dev

# 開発用ステージ
FROM base AS develop
COPY --from=goegoe0212/poetry-image:latest /root/.local /root/.local
RUN poetry config virtualenvs.create false

RUN --mount=type=cache,target=/var/lib/apt,sharing=locked \
    --mount=type=cache,target=/var/cache/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    git

COPY ./app/pyproject.toml ./app/poetry.lock /usr/src/app/
RUN poetry install

COPY ./ /usr/src/


# 本番用ステージ (dev依存なし)
FROM base AS production
WORKDIR /usr/src/app

COPY --from=prod-deps /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=prod-deps /usr/local/bin /usr/local/bin

COPY ./app /usr/src/app

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]