from pathlib import Path
from typing import Literal
from urllib.parse import quote

from pydantic import Field, SecretStr
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
    gemini_api_key: SecretStr = SecretStr('')
    tinyfish_api_key: SecretStr = SecretStr('')
    gemini_model: str = 'gemini-4-argon'
    congestion_calls_per_hour: int = Field(default=20, ge=0, le=1000)
    compliance_calls_per_hour: int = Field(default=60, ge=0, le=10000)
    compliance_concurrency: int = Field(default=6, ge=1, le=12)
    compliance_max_context_bytes: int = Field(default=3000000, ge=10000, le=16000000)

    def connection_uri(self):
        return self.mongodb_uri.replace('<db_password>', quote(self.mongodb_password.get_secret_value(), safe=''))


settings = Settings()
