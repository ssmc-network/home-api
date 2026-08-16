# ARGにはバージョン番号だけでなくイメージ参照そのものを入れる。
# `python:${PYTHON_VERSION}-slim-trixie` のようにタグを組み立てる書き方だと
# Renovateのdockerfileマネージャーが依存として認識できないため
# (兄弟リポジトリのDockerfileも同じ理由でこの形にしている)。
ARG PYTHON_IMAGE=python:3.13.12-slim-trixie

FROM ${PYTHON_IMAGE} AS base
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
FROM base AS dependencies
COPY --from=goegoe0212/poetry-image:latest /root/.local /root/.local
RUN poetry config virtualenvs.create false

COPY ./app/pyproject.toml ./app/poetry.lock /usr/src/app/
RUN poetry install --without dev

# 開発用ステージ
FROM base AS dev
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
FROM base AS prd
WORKDIR /usr/src/app

# このパスはPYTHON_IMAGEのマイナーバージョンと結びついている。Renovateが
# python:3.14系へ上げるPRを出した場合はここも追従が必要
# (追従漏れはCOPY元が存在せずビルドエラーになるため、CIで気づける)。
COPY --from=dependencies /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=dependencies /usr/local/bin /usr/local/bin

COPY ./app /usr/src/app

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]