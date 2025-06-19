import json
import logging
import uuid
from pathlib import Path

import redis
from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from yt_dlp import YoutubeDL  # type: ignore[import]

from settings.config import settings

router = APIRouter(tags=["Youtube Download"])

logger = logging.getLogger(__name__)

REDIS_QUEUE_KEY = "youtube_download_queue"
REDIS_STATUS_KEY = "youtube_download_statuses"


class YoutubeDownload(BaseModel):
    """youtubeのURL"""

    url: str


@router.post("/download")
def download(sp_args: YoutubeDownload, background_tasks: BackgroundTasks, request: Request) -> JSONResponse:
    try:
        redis_client = request.app.state.redis
        task_id = str(uuid.uuid4())
        redis_client.hset(REDIS_STATUS_KEY, task_id, json.dumps({"status": "queued", "error": None}))
        redis_client.rpush(REDIS_QUEUE_KEY, json.dumps({"task_id": task_id, "url": sp_args.url}))
        background_tasks.add_task(process_queue, request)
        return JSONResponse({"task_id": task_id, "message": "キューに登録しました"})
    except redis.exceptions.ConnectionError as e:
        # Redisに接続できない場合のエラー応答
        return JSONResponse({"error": "Redisに接続できません", "detail": str(e)}, status_code=503)
    except redis.exceptions.RedisError as e:
        # その他のRedis関連エラー
        return JSONResponse({"error": "Redisエラー", "detail": str(e)}, status_code=500)


@router.get("/download/status")
def download_status(request: Request) -> JSONResponse:
    try:
        redis_client = request.app.state.redis
        statuses = redis_client.hgetall(REDIS_STATUS_KEY)
        return JSONResponse({k: json.loads(v) for k, v in statuses.items()})
    except redis.exceptions.ConnectionError as e:
        return JSONResponse({"error": "Redisに接続できません", "detail": str(e)}, status_code=503)
    except redis.exceptions.RedisError as e:
        return JSONResponse({"error": "Redisエラー", "detail": str(e)}, status_code=500)
    except Exception as e:
        return JSONResponse({"error": "不明なエラー", "detail": str(e)}, status_code=500)


def process_queue(request: Request) -> None:
    try:
        redis_client = request.app.state.redis
        while True:
            try:
                item = redis_client.lpop(REDIS_QUEUE_KEY)
            except redis.exceptions.ConnectionError:
                # ログ出力や通知など
                logger.exception("Redis接続エラー")
                break
            except redis.exceptions.RedisError:
                logger.exception("Redisエラー")
                break

            if not item:
                break
            data = json.loads(item)
            task_id = data["task_id"]
            url = data["url"]

            try:
                video_title = get_youtube_title(url)
                redis_client.hset(
                    REDIS_STATUS_KEY,
                    task_id,
                    json.dumps({"status": "processing", "error": None, "title": video_title}),
                )
                download_youtube(url, settings.output_dir)
                redis_client.hset(
                    REDIS_STATUS_KEY,
                    task_id,
                    json.dumps({"status": "done", "error": None, "title": video_title}),
                )
            except Exception as e:
                redis_client.hset(
                    REDIS_STATUS_KEY,
                    task_id,
                    json.dumps(
                        {
                            "status": "error",
                            "error": str(e),
                            "title": video_title if "video_title" in locals() else "unknown",
                        },
                    ),
                )
    except Exception:
        # Redis自体の初期取得失敗やその他例外
        logger.exception("process_queue全体でのエラー")


def download_youtube(url: str, output_dir: str) -> None:
    path_out_dir = Path(output_dir)
    ydl_opts = {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "outtmpl": str(path_out_dir / "%(title).50s.mp4"),
        "merge_output_format": "mp4",
        "postprocessors": [],
    }
    with YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])


def get_youtube_title(url: str) -> str:
    with YoutubeDL({"quiet": True}) as ydl:
        info = ydl.extract_info(url, download=False)
        return info.get("title", "unknown")
