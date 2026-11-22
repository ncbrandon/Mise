from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://mise:mise@db:5432/mise"
    secret_key: str = "change-me"
    public_url: str = "http://localhost:8000"  # used to build share links
    allow_registration: bool = True
    token_days: int = 365
    media_dir: str = "/data/media"

    # Public "reader": GET /https://some-site/recipe renders a clean page without login
    public_reader: bool = True
    # Allow fetching hosts on private networks (off by default: SSRF protection)
    allow_private_fetch: bool = False

    # Any OpenAI-compatible endpoint: OpenAI, OpenRouter, Ollama (http://ollama:11434/v1), LM Studio...
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_vision_model: str = ""  # defaults to llm_model
    llm_timeout: int = 120

    # Speech-to-text for videos with no captions (OpenAI-compatible /audio/transcriptions)
    transcribe_base_url: str = ""  # defaults to llm_base_url
    transcribe_api_key: str = ""   # defaults to llm_api_key
    transcribe_model: str = ""     # e.g. "whisper-1"; empty disables transcription

    ytdlp_cookies_file: str = ""   # Netscape cookies.txt, helps with Instagram

    # Home Assistant shopping list sync (optional)
    home_assistant_url: str = ""          # e.g. http://192.168.1.10:8123
    home_assistant_token: str = ""        # long-lived access token (HA profile -> Security)
    home_assistant_todo_entity: str = "todo.shopping_list"

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_model) and (bool(self.llm_api_key) or "api.openai.com" not in self.llm_base_url)


@lru_cache
def get_settings() -> Settings:
    return Settings()
