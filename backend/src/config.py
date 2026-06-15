import os
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    app_name: str = "CloudRAG-Hub"
    app_version: str = "1.0.0"
    debug: bool = True
    host: str = "0.0.0.0"
    port: int = 8080
    frontend_port: int = 8081

    jwt_secret_key: str = "dev-secret-change-in-production"
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
    dify_dataset_id: str = "45725dcd-82f3-45b9-8116-ce9ac9fac096"
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
