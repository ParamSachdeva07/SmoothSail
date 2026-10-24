from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from urllib.parse import quote
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / '.env', extra='ignore')
    tideline_mode: Literal['demo', 'mongo'] = 'demo'
    mongodb_uri: str = 'mongodb://localhost:27019'
    mongodb_db: str = 'tideline'
    mongodb_password: SecretStr = SecretStr('')
    data_dir: Path = ROOT / 'data'
    copernicus_username: str = ''
    copernicus_password: SecretStr = SecretStr('')
    auto_refresh_forecasts: bool = False
    tideline_internal_token: SecretStr = SecretStr('')
    route_timeout_seconds: int = Field(default=45, ge=5, le=180)
    max_candidates: int = Field(default=8, ge=3, le=20)

    def connection_uri(self):
        return self.mongodb_uri.replace('<db_password>', quote(self.mongodb_password.get_secret_value(), safe=''))


settings = Settings()
