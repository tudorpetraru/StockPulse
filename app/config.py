from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    environment: str = Field(default="development", alias="ENVIRONMENT")
    host: str = Field(default="127.0.0.1", alias="HOST")
    port: int = Field(default=8000, alias="PORT")
    db_path: Path = Field(default=Path("data/stockpulse.db"), alias="DB_PATH")
    cache_dir: Path = Field(default=Path("data/cache"), alias="CACHE_DIR")
    cache_size_limit_bytes: int = Field(default=500 * 1024 * 1024, alias="CACHE_SIZE_LIMIT")
    refresh_interval_min: int = Field(default=15, alias="REFRESH_INTERVAL_MIN")
    market_tz: str = Field(default="US/Eastern", alias="MARKET_TZ")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # Scheduler / prediction windows
    prediction_snapshot_hour_et: int = Field(default=18, alias="PREDICTION_SNAPSHOT_HOUR_ET")
    prediction_evaluation_hour_et: int = Field(default=18, alias="PREDICTION_EVALUATION_HOUR_ET")
    prediction_evaluation_minute_et: int = Field(default=30, alias="PREDICTION_EVALUATION_MINUTE_ET")
    prediction_recompute_hour_et: int = Field(default=19, alias="PREDICTION_RECOMPUTE_HOUR_ET")
    prediction_recompute_minute_et: int = Field(default=0, alias="PREDICTION_RECOMPUTE_MINUTE_ET")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
