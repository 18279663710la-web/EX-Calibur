import os
import secrets
from pathlib import Path

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    app_name: str = "CloudRAG-Hub"
    app_version: str = "1.0.0"
    debug: bool = True
    host: str = "0.0.0.0"
    port: int = 8080
    frontend_port: int = 8081

    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    access_token_expire_seconds: int = 7200
    refresh_token_expire_seconds: int = 604800

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "cloudrag"
    postgres_user: str = "cloudrag"
    postgres_password: str = "cloudrag"

    dify_base_url: str = "https://api.dify.ai/v1"
    dify_api_key: str = ""
    dify_dataset_api_key: str = ""
    dify_dataset_id: str = ""
    dify_internal_key: str = ""
    dify_timeout_seconds: int = 120

    max_upload_size_mb: int = 15
    upload_dir: str = "./uploads"

    weixin_base_url: str = "https://ilinkai.weixin.qq.com"
    weixin_cdn_base_url: str = "https://novac2c.cdn.weixin.qq.com/c2c"
    weixin_token: str = ""
    weixin_credentials_path: str = "./uploads/weixin_credentials.json"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


def _ensure_jwt_secret(settings: Settings) -> None:
    if settings.jwt_secret_key and not settings.jwt_secret_key.startswith("change-me"):
        return
    secret_file = Path(settings.upload_dir) / ".jwt_secret"
    if secret_file.exists():
        settings.jwt_secret_key = secret_file.read_text().strip()
        return
    generated = secrets.token_hex(32)
    secret_file.parent.mkdir(parents=True, exist_ok=True)
    secret_file.write_text(generated)
    settings.jwt_secret_key = generated


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    _ensure_jwt_secret(settings)
    return settings
