from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    BOT_TOKEN: str
    DATABASE_URL: str
    COMET_API_KEY: str
    BOT_USERNAME: str | None = None  # НОВОЕ: username бота для реф-ссылок
    ADM_GROUP_ID = -5075627878

    # .env ищем в корне проекта, откуда ты запускаешь `python src/main.py`
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
