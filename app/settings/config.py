from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    title: str = Field(default="FastAPI")
    description: str = Field(default="My App Description")
    version: str = Field(default="1.0.0")
    openapi_url: str = Field(default="/openapi.json")
    docs_url: str = Field(default="/docs")
    prefix_url: str = Field(default="")
    output_dir: str = Field(default="/data")

    redis_host: str = Field(default="redis-service")
    redis_port: int = Field(default=6379)
    redis_max_connections: int = Field(default=10)


settings = Settings()
