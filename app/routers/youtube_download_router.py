import redis
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from modules import download_queue

router = APIRouter(tags=["Youtube Download"])


class YoutubeDownload(BaseModel):
    """youtubeのURL"""

    url: str


@router.post("/download")
def download(sp_args: YoutubeDownload, request: Request) -> JSONResponse:
    # キューへ積むだけで、実際のダウンロードは lifespan で起動した常駐ワーカーが行う。
    try:
        task_id = download_queue.enqueue(request.app.state.redis, sp_args.url)
    except redis.exceptions.ConnectionError as e:
        # Redisに接続できない場合のエラー応答
        return JSONResponse({"error": "Redisに接続できません", "detail": str(e)}, status_code=503)
    except redis.exceptions.RedisError as e:
        # その他のRedis関連エラー
        return JSONResponse({"error": "Redisエラー", "detail": str(e)}, status_code=500)
    return JSONResponse({"task_id": task_id, "message": "キューに登録しました"})


@router.get("/download/status")
def download_status(request: Request) -> JSONResponse:
    try:
        statuses = download_queue.fetch_statuses(request.app.state.redis)
    except redis.exceptions.ConnectionError as e:
        return JSONResponse({"error": "Redisに接続できません", "detail": str(e)}, status_code=503)
    except redis.exceptions.RedisError as e:
        return JSONResponse({"error": "Redisエラー", "detail": str(e)}, status_code=500)
    except Exception as e:
        return JSONResponse({"error": "不明なエラー", "detail": str(e)}, status_code=500)
    return JSONResponse(statuses)


@router.delete("/download/all")
def delete_all_downloads(request: Request) -> JSONResponse:
    try:
        download_queue.clear_all(request.app.state.redis)
    except redis.exceptions.ConnectionError as e:
        return JSONResponse({"error": "Redisに接続できません", "detail": str(e)}, status_code=503)
    except redis.exceptions.RedisError as e:
        return JSONResponse({"error": "Redisエラー", "detail": str(e)}, status_code=500)
    except Exception as e:
        return JSONResponse({"error": "不明なエラー", "detail": str(e)}, status_code=500)
    return JSONResponse({"message": "すべてのステータスと未処理のキューを削除しました"})
