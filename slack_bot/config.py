import os
import json
from typing import Dict, List

# Load environment variables from .env files (root and slack_bot/.env) if present
try:
    from dotenv import load_dotenv
    # Root .env
    load_dotenv()
    # slack_bot/.env (alongside this file)
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except Exception:
    # dotenv is optional; ignore if unavailable
    pass


def get_env(name: str, default: str | None = None, required: bool = False) -> str:
    v = os.getenv(name, default)
    if required and not v:
        raise RuntimeError(f"Missing required env: {name}")
    assert v is not None
    return v


class Settings:
    def __init__(self) -> None:
        # Slack
        # Allow offline mode without Slack creds
        self.slack_offline: bool = os.getenv("SLACK_OFFLINE", "0").lower() in {"1", "true", "yes"}
        self.slack_bot_token: str = get_env("SLACK_BOT_TOKEN", required=not self.slack_offline)
        self.slack_signing_secret: str = get_env("SLACK_SIGNING_SECRET", required=not self.slack_offline)
        # TaskFlow API base URL e.g. https://<ngrok>/v1 or http://localhost:8000/v1
        self.taskflow_base_url: str = get_env("TASKFLOW_API_BASE_URL", "http://127.0.0.1:8000")
        self.taskflow_token: str = get_env("TASKFLOW_API_TOKEN", required=True)
        # Comma separated Slack user IDs to DM daily
        self.daily_user_ids: List[str] = [u for u in get_env("DAILY_USER_IDS", "").split(",") if u]
        # Optional Slack->TaskFlow user mapping: JSON string {"Uxxxx":"user-key-or-email"}
        raw = get_env("USER_MAP_JSON", "{}")
        try:
            self.user_map: Dict[str, str] = json.loads(raw)
        except json.JSONDecodeError:
            self.user_map = {}
        # Scheduler timezone and time
        self.jst_hour: int = int(get_env("JST_HOUR", "9"))
        self.jst_minute: int = int(get_env("JST_MINUTE", "0"))
        # Spool directory for failed submissions
        self.spool_dir: str = get_env("SPOOL_DIR", os.path.join(os.path.dirname(__file__), "spool"))
        # Flask port
        self.port: int = int(get_env("PORT", "3000"))
        # Log level
        self.log_level: str = get_env("LOG_LEVEL", "INFO")
        # Admin trigger token (optional) for rehearsal endpoints
        self.admin_token: str | None = os.getenv("ADMIN_TOKEN")
        # OpenAI
        self.openai_api_key: str | None = os.getenv("OPENAI_API_KEY")
        self.openai_model: str = get_env("OPENAI_MODEL", "gpt-4o-mini")
        self.openai_base_url: str | None = os.getenv("OPENAI_BASE_URL")
        self.openai_temperature: float = float(get_env("OPENAI_TEMPERATURE", "0.2"))
        self.openai_max_tokens: int = int(get_env("OPENAI_MAX_TOKENS", "2000"))

    @property
    def openai_enabled(self) -> bool:
        return bool(self.openai_api_key)


settings = Settings()
