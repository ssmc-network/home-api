"""ダウンロードキューとタスク状態をRedis上で扱うモジュール。

キュー(リスト)とタスク状態(ハッシュ)の読み書き、およびキューを消化し続ける
常駐ワーカーを提供する。HTTP層(routers)はこのモジュール越しにRedisを触る。
"""

import asyncio
import contextlib
import json
import uuid
from typing import Any

import redis

from core.log_modules import log_application
from modules.youtube_module import download_youtube, get_youtube_title
from settings.config import settings

logger = log_application(__name__)

# home-discord-bot と共有しているキー。ステータスハッシュの値のスキーマ
# (status / error / title)まで含めてプロセス間の契約になっているため、
# 変更する場合は必ずボット側と同時に行うこと(CLAUDE.md参照)。
REDIS_QUEUE_KEY = "youtube_download_queue"
REDIS_STATUS_KEY = "youtube_download_statuses"


def write_status(
    redis_client: redis.Redis,
    task_id: str,
    status: str,
    *,
    title: str | None = None,
    error: str | None = None,
) -> None:
    """タスクの状態をステータスハッシュへ書き込む。

    title はタイトルが判明している場合のみキーごと含める。ボット側は title が
    無い場合に「タイトル取得中」へフォールバックするため、未確定の段階で
    null を書き込まないようにしている。
    """
    payload: dict[str, str | None] = {"status": status, "error": error}
    if title is not None:
        payload["title"] = title
    redis_client.hset(REDIS_STATUS_KEY, task_id, json.dumps(payload))


def enqueue(redis_client: redis.Redis, url: str) -> str:
    """URLをキューへ積み、採番したタスクIDを返す。"""
    task_id = str(uuid.uuid4())
    write_status(redis_client, task_id, "queued")
    redis_client.rpush(REDIS_QUEUE_KEY, json.dumps({"task_id": task_id, "url": url}))
    return task_id


def fetch_statuses(redis_client: redis.Redis) -> dict[str, Any]:
    """全タスクの状態を取得する。"""
    statuses: dict[str, str] = redis_client.hgetall(REDIS_STATUS_KEY)  # type: ignore[assignment]
    return {task_id: json.loads(value) for task_id, value in statuses.items()}


def clear_all(redis_client: redis.Redis) -> None:
    """全タスクの状態と、未処理のキューをまとめて削除する。

    ステータスだけを消すとキューに残ったジョブが後から「状態の無いジョブ」として
    処理されてしまうため、キューも併せて削除する。ボットが持つ
    youtube_download_notified_statuses はボット側の管轄なので触らない
    (ステータスが消えたことをボット自身が検知して片付ける)。
    """
    redis_client.delete(REDIS_STATUS_KEY, REDIS_QUEUE_KEY)


def pop_job(redis_client: redis.Redis) -> dict[str, str] | None:
    """キューからジョブを1件取り出す。timeout まで待って空ならNoneを返す。"""
    popped = redis_client.blpop([REDIS_QUEUE_KEY], timeout=settings.queue_pop_timeout_seconds)
    if popped is None:
        return None
    _, raw_job = popped
    job: dict[str, str] = json.loads(raw_job)
    return job


def process_job(redis_client: redis.Redis, job: dict[str, str]) -> None:
    """ジョブ1件を処理し、進捗をステータスハッシュへ反映する。"""
    task_id = job["task_id"]
    url = job["url"]
    # タイトル取得より前で失敗した場合に備えて先に初期化しておく
    # (以前は except 節で locals() を覗いて判定していた)。
    video_title = "unknown"
    try:
        video_title = get_youtube_title(url)
        write_status(redis_client, task_id, "processing", title=video_title)
        download_youtube(url, settings.output_dir)
        write_status(redis_client, task_id, "done", title=video_title)
    except Exception as e:
        logger.exception("タスク %s のダウンロードに失敗しました", task_id)
        write_status(redis_client, task_id, "error", title=video_title, error=str(e))


async def _sleep_or_stop(stop_event: asyncio.Event, seconds: float) -> None:
    """stop_event がセットされるまで、最大 seconds 秒待つ。

    素の asyncio.sleep で待つとバックオフ中はシャットダウンに反応できないため、
    停止指示が来た時点で待機を打ち切れるようにしている。
    """
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stop_event.wait(), timeout=seconds)


async def run_worker(redis_client: redis.Redis, stop_event: asyncio.Event, name: str) -> None:
    """キューを消化し続ける常駐ワーカー。

    Redisの blpop も yt-dlp のダウンロードもブロッキングなので、どちらも
    asyncio.to_thread でスレッドへ逃がし、イベントループを止めないようにする。
    ワーカーの本数(settings.download_workers)がそのまま同時ダウンロード数の
    上限になる。
    """
    logger.info("ダウンロードワーカー %s を開始しました", name)
    while not stop_event.is_set():
        try:
            job = await asyncio.to_thread(pop_job, redis_client)
        except redis.RedisError:
            logger.exception("キューの取得に失敗しました。%s秒後に再試行します", settings.queue_error_backoff_seconds)
            await _sleep_or_stop(stop_event, settings.queue_error_backoff_seconds)
            continue

        if job is None:
            continue

        try:
            await asyncio.to_thread(process_job, redis_client, job)
        except Exception:
            # 1件の失敗でワーカーを落とさない。ここで抜けると以降のジョブが
            # 一切消化されなくなるため、意図的に広く捕捉している。
            logger.exception("ジョブの処理中に想定外のエラーが発生しました")

    logger.info("ダウンロードワーカー %s を停止しました", name)
