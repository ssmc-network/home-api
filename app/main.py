import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from core.log_modules import log_application
from modules.download_queue import run_worker
from modules.redis_module import RedisConnector
from routers import operation_check, youtube_download_router
from settings.config import settings

logger = log_application(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Redis接続とダウンロードワーカーのライフサイクルを管理する。

    キューの消化はリクエスト駆動(BackgroundTasks)ではなく、ここで起動する
    常駐ワーカーが行う。これによりPOSTが来なくても積まれたジョブが処理され、
    同時ダウンロード数もワーカー本数で上限が決まる。
    """
    redis_connector = RedisConnector()
    redis_client = redis_connector.get_connection()
    app.state.redis = redis_client

    stop_event = asyncio.Event()
    workers = [
        asyncio.create_task(
            run_worker(redis_client, stop_event, f"worker-{index}"),
            name=f"download-worker-{index}",
        )
        for index in range(settings.download_workers)
    ]
    logger.info("ダウンロードワーカーを %s 個起動しました", len(workers))

    try:
        yield
    finally:
        # 処理中のダウンロードが終わるのを待ってから停止する。待ち切れなかった
        # ワーカーだけキャンセルし、シャットダウンが無限に延びないようにする。
        stop_event.set()
        if workers:
            _done, pending = await asyncio.wait(workers, timeout=settings.worker_shutdown_timeout_seconds)
            for task in pending:
                logger.warning("ワーカー %s の終了を待てなかったためキャンセルします", task.get_name())
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
        redis_connector.close()
        logger.info("Redis接続をクローズしました")


app = FastAPI(
    title=settings.title,
    description=settings.description,
    version=settings.version,
    openapi_url=settings.prefix_url + settings.openapi_url,
    docs_url=settings.prefix_url + settings.docs_url,
    redoc_url=None,
    lifespan=lifespan,
)

app.include_router(operation_check.router, prefix=settings.prefix_url)
app.include_router(youtube_download_router.router, prefix=settings.prefix_url)
