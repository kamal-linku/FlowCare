from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./flowcare.db"
    jwt_secret: str = ""
    access_token_minutes: int = 720
    cors_origins: str = "http://localhost:5173,http://localhost:4173"
    flowcare_demo_password: str | None = None

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[3] / ".env",
        env_ignore_empty=True,
        extra="ignore",
    )

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def sqlite_path(self) -> Path | None:
        if not self.database_url.startswith("sqlite:///"):
            return None
        path = Path(self.database_url.removeprefix("sqlite:///"))
        return path if path.is_absolute() else Path.cwd() / path


settings = Settings()
