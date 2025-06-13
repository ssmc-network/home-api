import redis
from fastapi import HTTPException

from settings.config import settings


class RedisConnector:
    def __init__(
        self,
        host: str = settings.redis_host,
        port: int = settings.redis_port,
        max_connections: int = settings.redis_max_connections,
    ) -> None:
        """初期化"""
        self.host = host
        self.port = port
        self._pool: redis.ConnectionPool | None = None
        self.max_connections = max_connections

    def _initialize_pool(self) -> None:
        if self._pool is None:
            try:
                self._pool = redis.ConnectionPool(
                    host=self.host,
                    port=self.port,
                    max_connections=self.max_connections,
                    decode_responses=True,
                )
            except redis.ConnectionError as e:
                raise HTTPException(status_code=500, detail=f"Redis connection error: {e!s}") from e

    def get_connection(self) -> redis.Redis:
        if self._pool is None:
            self._initialize_pool()
        return redis.Redis(connection_pool=self._pool)
