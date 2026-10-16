"""Typed settings for every Lattice role, read from LATTICE_* environment variables."""

from pydantic import Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_PREFIX = "LATTICE_"


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix=ENV_PREFIX, extra="ignore")

    neo4j_uri: str
    neo4j_user: str
    neo4j_password: SecretStr
    redis_url: str
    approver_token: SecretStr

    mcp_url: str = "http://localhost:8000/mcp"
    # Model string understood by Pydantic AI; the exact Gemini model is settled in U6.
    model: str = "google-gla:gemini-2.5-flash"
    gemini_api_key: SecretStr | None = None
    llm_requests_per_minute: int = Field(default=10, ge=1)
    investigation_step_budget: int = Field(default=12, ge=1)
    risk_threshold: float = Field(default=0.6, gt=0, lt=1)


def load_settings(env_file: str | None = ".env") -> Settings:
    """Load settings, turning validation errors into one message that names each variable."""
    try:
        return Settings(_env_file=env_file)
    except ValidationError as exc:
        problems = []
        for error in exc.errors():
            field = str(error["loc"][0])
            problems.append(f"{ENV_PREFIX}{field.upper()}: {error['msg']}")
        raise ConfigError("Invalid configuration:\n  " + "\n  ".join(problems)) from None
