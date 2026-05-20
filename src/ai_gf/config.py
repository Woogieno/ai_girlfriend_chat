from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    ig_username: str
    ig_password: str
    owner_ig_user_id: str

    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:14b-instruct-q4_K_M"
    ollama_aux_model: str = "qwen2.5:3b"

    timezone: str = "Asia/Seoul"
    daily_proactive_cap: int = 20
    daily_response_cap: int = 25
    poll_min_seconds: int = 30
    poll_max_seconds: int = 90
    send_jitter_min_seconds: int = 30
    send_jitter_max_seconds: int = 300
    idle_detection_hours: int = 4

    data_dir: Path = Path("data")
    db_path: Path = Path("data/ai_gf.db")
    ig_session_path: Path = Path("data/ig_session.json")
    log_path: Path = Path("data/ai_gf.log")


def load_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
