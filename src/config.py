from typing import List

from pydantic import field_validator, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    BOT_TOKEN: str
    DATABASE_URL: str
    COMET_API_KEY: str

    model_config = SettingsConfigDict(
        env_file="../.env",
        extra="ignore",
    )

settings = Settings()