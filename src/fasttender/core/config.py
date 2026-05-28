"""Конфигурация приложения через переменные окружения (Pydantic Settings).

Все внешние зависимости (БД, Redis, файловое хранилище, LLM) подключаются
через конфиг — это требование deployment-agnostic архитектуры (раздел 5.4).
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, PostgresDsn, RedisDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="FT_",
        extra="ignore",
    )

    # Окружение
    environment: str = Field(default="dev", description="dev / staging / prod")
    debug: bool = Field(default=False)

    # БД
    database_url: PostgresDsn = Field(
        default="postgresql+asyncpg://fasttender:fasttender@localhost:5432/fasttender",  # type: ignore[arg-type]
        description="Async URL для приложения (asyncpg драйвер)",
    )
    database_url_sync: PostgresDsn = Field(
        default="postgresql+psycopg://fasttender:fasttender@localhost:5432/fasttender",  # type: ignore[arg-type]
        description="Sync URL для Alembic",
    )

    # Очередь и кэш
    redis_url: RedisDsn = Field(
        default="redis://localhost:6379/0",  # type: ignore[arg-type]
    )

    # Файловое хранилище (в Фазе 1 — локальная ФС; в Фазе 2 — S3)
    upload_dir: Path = Field(default=Path("/var/lib/fasttender/uploads"))

    # CORS
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    # Лимиты
    max_upload_size_mb: int = Field(default=50)

    # Матчер — стартовые пороги (раздел 4.5, 6.1 A3)
    confidence_auto_confirm: float = Field(default=0.9)
    confidence_min: float = Field(default=0.5)

    @property
    def database_url_str(self) -> str:
        return str(self.database_url)

    @property
    def database_url_sync_str(self) -> str:
        return str(self.database_url_sync)

    @property
    def redis_url_str(self) -> str:
        return str(self.redis_url)


@lru_cache
def get_settings() -> Settings:
    return Settings()
