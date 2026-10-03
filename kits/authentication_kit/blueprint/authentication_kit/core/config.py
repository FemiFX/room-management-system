from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="POSTBUCH_", env_file=".env", extra="ignore")

    env: str = "development"
    app_name: str = "Postbuch"
    secret_key: str = "dev-secret-key"
    database_url: str = "postgresql+psycopg://authentication_kit:authentication_kit@db:5432/authentication_kit"
    session_cookie_name: str = "authentication_kit_session"
    storage_root: Path = Path("var/storage")

    oidc_enabled: bool = True
    oidc_server_metadata_url: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_scopes: str = "openid profile email"
    oidc_admin_emails: Annotated[list[str], NoDecode] = Field(default_factory=list)
    dev_auth_enabled: bool = False

    imap_poll_seconds: int = 300

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_address: str | None = None
    smtp_use_tls: bool = True

    ocr_language: str = "deu+eng"
    ocr_min_text_length: int = 80

    @field_validator("oidc_admin_emails", mode="before")
    @classmethod
    def parse_admin_emails(cls, value: object) -> list[str]:
        if value is None or value == "":
            return []
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return []


@lru_cache
def get_settings() -> Settings:
    return Settings()
