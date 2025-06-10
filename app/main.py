from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from modules.redis_module import RedisConnector
from routers import operation_check, youtube_download_router
from settings.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    app.state.redis = RedisConnector().get_connection()
    yield


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
