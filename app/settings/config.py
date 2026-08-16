from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    service: str = Field(default="home-api")
    tz: str = Field(default="Asia/Tokyo")
    loglevel: str = Field(default="INFO")
    title: str = Field(default="FastAPI")
    description: str = Field(default="My App Description")
    version: str = Field(default="1.0.0")
    openapi_url: str = Field(default="/openapi.json")
    docs_url: str = Field(default="/docs")
    prefix_url: str = Field(default="")
    output_dir: str = Field(default="/data")

    # 常駐ワーカーの本数 = 同時にダウンロードが走る上限
    download_workers: int = Field(default=1)
    # ワーカーがキューを待つ時間。この値がそのままシャットダウンの最大待ち時間になる
    queue_pop_timeout_seconds: int = Field(default=5)
    # Redisへの接続が切れている間、ワーカーが再試行するまでの待ち時間
    queue_error_backoff_seconds: float = Field(default=5)
    # シャットダウン時、処理中のダウンロードの完了を待つ上限
    worker_shutdown_timeout_seconds: float = Field(default=30)

    redis_host: str = Field(default="redis-service")
    redis_port: int = Field(default=6379)
    redis_max_connections: int = Field(default=10)


settings = Settings()
