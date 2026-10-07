import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent.parent
# Real environment variables take precedence over .env.
load_dotenv(ROOT / ".env", override=False)


@dataclass(frozen=True)
class Settings:
    providers_path: str = field(
        default_factory=lambda: os.getenv("PROVIDERS_PATH", str(ROOT / "data" / "providers.json"))
    )
    database_url: str = field(
        default_factory=lambda: os.getenv("DATABASE_URL", f"sqlite:///{ROOT / 'data' / 'nearbyai.db'}")
    )
    # "anthropic" uses the Claude API; "rules" uses the offline rule-based
    # extractor/writer (no API key needed). "auto" picks anthropic when a key exists.
    llm_backend: str = field(default_factory=lambda: os.getenv("LLM_BACKEND", "auto"))
    llm_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", "claude-sonnet-5-5"))
    llm_effort: str = field(default_factory=lambda: os.getenv("LLM_EFFORT", "low"))
    extraction_attempts: int = 3
    demo_access_code: str | None = field(default_factory=lambda: os.getenv("DEMO_ACCESS_CODE") or None)
    frontend_dir: str = field(default_factory=lambda: os.getenv("FRONTEND_DIR", str(ROOT / "frontend")))


settings = Settings()
