# ==========================================
# グローバル設定
# ==========================================
# dhi.io は Docker Hardened Images 専用レジストリ。pull には
# `docker login dhi.io`(Docker Hubの認証情報)が必要。
# タグは浮動(latestの中身が無断で変わる)ため、digestで固定しRenovateに
# 更新PRを出させている(更新検知の仕組みはCLAUDE.md参照)。
ARG PYTHON_DEV_IMAGE=dhi.io/python:3-debian-dev@sha256:a178ee6488b38c58c333eff50675717a314a15f006ede24ed121eaadc00c984b
ARG PYTHON_PRD_IMAGE=dhi.io/python:3@sha256:ca15493305d675cccc8f3ea8ee5cdff5f4904ae8f90ab9fd26a0a5cbe5ad984a
# yt-dlpが映像と音声を別々に取得してmp4へマージするためにffmpegが必須だが、
# 本番用の dhi.io/python:3 は最小構成でパッケージマネージャを持たないため
# apt等でインストールできない。このイメージは外部依存を持たない静的PIE
# バイナリとしてビルドされたffmpeg/ffprobeを提供するので、バイナリ2個を
# COPYするだけで済む(共有ライブラリの持ち込みが不要)。
ARG FFMPEG_IMAGE=mwader/static-ffmpeg:9.0@sha256:b90574a4e2ae62b763c39c384526689e7eb435da6398f4fb3f6c3f1c6a14ce33
ARG POETRY_VERSION=2.4.1


# ==========================================
# ffmpeg/ffprobe の取得元
# ==========================================
# COPY --from= で直接イメージ参照を書かず一度ステージ化しているのは、
# ARGの展開を FROM 行に閉じ込めてRenovateに追跡させるため。
FROM ${FFMPEG_IMAGE} AS ffmpeg


# ==========================================
# ベースイメージ(依存関係のビルド用 = devバリアント)
# ==========================================
FROM ${PYTHON_DEV_IMAGE} AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_INSTALLER_MAX_WORKERS=10 \
    POETRY_VIRTUALENVS_CREATE=true \
    POETRY_VIRTUALENVS_IN_PROJECT=true
WORKDIR /usr/src/app


# ==========================================
# 依存関係のビルド(本番用: 通常依存のみ)
# ==========================================
# poetry自体はここ(dependencies/dev-dependencies)にだけ入る。dev/prdへ
# 引き継ぐのは`poetry install`が作る.venv(プロジェクト内仮想環境)のみ
# (下のdev/prdステージのCOPY --fromを参照)。poetry自身やそのビルド時限りの
# 依存が本番イメージに紛れ込むのを防ぐための構成。
FROM base AS dependencies
ARG POETRY_VERSION

RUN pip install --upgrade --no-cache-dir pip && \
    pip install --no-cache-dir poetry=="${POETRY_VERSION}" && \
    poetry config virtualenvs.options.no-pip true

COPY ./app/pyproject.toml ./app/poetry.lock /usr/src/app/
RUN poetry install --without dev --no-root && \
    poetry cache clear pypi --all


# ==========================================
# 依存関係のビルド(devグループを含む完全版)
# ==========================================
FROM dependencies AS dev-dependencies

RUN poetry install --no-root && \
    poetry cache clear pypi --all


# ==========================================
# 開発用イメージ (dev)
# ==========================================
FROM base AS dev
ENV VIRTUAL_ENV=/usr/src/app/.venv \
    PATH=/usr/src/app/.venv/bin:$PATH

COPY --from=ffmpeg /ffmpeg /ffprobe /usr/local/bin/
COPY --from=dev-dependencies /usr/src/app/.venv /usr/src/app/.venv
COPY ./ /usr/src/


# ==========================================
# 本番用イメージ (prd)
# ==========================================
# devバリアントではなく、最小構成のprdバリアントから作る。
FROM ${PYTHON_PRD_IMAGE} AS prd
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/usr/src/app/.venv \
    PATH=/usr/src/app/.venv/bin:$PATH
WORKDIR /usr/src/app

COPY --from=ffmpeg /ffmpeg /ffprobe /usr/local/bin/
COPY --from=dependencies /usr/src/app/.venv /usr/src/app/.venv
COPY ./app /usr/src/app

# 最小構成イメージにはシェルが無いためexec形式で指定する。コンソール
# スクリプト(.venv/bin/uvicorn)ではなく python -m で起動しているのは、
# PATH解決やshebangに依存する要素を1つ減らすため。
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
