from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RMS_", env_file=".env", extra="ignore")

    env: str = "development"
    app_name: str = "Room Management System"
    secret_key: str = "dev-secret"
    database_url: str = "postgresql+psycopg://rms:rms@postgres:5432/rms"
    session_cookie_name: str = "rms_session"
    session_secure: bool = False
    default_timezone: str = "Europe/Berlin"
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    supported_languages: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["de", "en",]
    )
    default_language: str = "en"
    babel_translation_directories: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["translations"])

    oidc_enabled: bool = True
    oidc_server_metadata_url: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_scopes: str = "openid profile email"
    dev_auth_enabled: bool = False

    nextcloud_sync_enabled: bool = False
    nextcloud_url: str = ""
    nextcloud_admin_user: str = ""
    nextcloud_app_password: str = ""
    nextcloud_ocs_version: str = "v2"
    nextcloud_timeout_s: int = 30
    nextcloud_page_size: int = 100

    redis_url: str = "redis://redis:6379/0"

    s3_endpoint_url: str = "http://minio:9000"
    s3_region: str = "us-east-1"
    s3_access_key_id: str = "minioadmin"
    s3_secret_access_key: str = "minioadmin"
    s3_bucket: str = "rms-dev"
    s3_key_prefix: str = "rms"
    s3_addressing_style: str = "path"
    s3_auto_create_bucket: bool = False

    document_url_expire_seconds: int = 900

    # --- outbound mail ---
    # Off by default: a fresh clone logs what it would have sent instead of
    # needing a reachable SMTP server. Everything else still works.
    mail_enabled: bool = False
    mail_host: str = "localhost"
    mail_port: int = 587
    mail_username: str = ""
    mail_password: str = ""
    mail_use_tls: bool = True  # STARTTLS on a plain connection
    mail_use_ssl: bool = False  # implicit TLS from the first byte
    mail_from: str = "no-reply@example.com"
    mail_from_name: str = ""
    mail_reply_to: str = ""
    mail_admin_recipients: Annotated[list[str], NoDecode] = Field(default_factory=list)
    mail_timeout_s: int = 20

    #: How many reverse proxies sit in front of RMS. 0 means none, and
    #: X-Forwarded-For is ignored entirely -- trusting it without a proxy lets
    #: any caller forge their address and slip the rate limiter.
    trusted_proxy_count: int = 0

    #: Absolute base for links in emails. Not optional: a Celery task has no
    #: request to derive a host from, so without this a manage link is unusable.
    public_base_url: str = "http://localhost:8001"

    # --- branding ---
    #: Everything a visitor sees that names or styles the operating
    #: organisation comes from here. Nothing is hardcoded in templates, so one
    #: deployment's identity never leaks into another's. Empty values render
    #: nothing rather than a placeholder. See docs/branding.md.
    brand_name: str = "Room Booking"
    #: Full legal name for the email footer, e.g. "Example Association e.V.".
    brand_legal_name: str = ""
    #: Absolute URL or a path under /static. Empty renders brand_name as text.
    brand_logo_url: str = ""
    brand_website_url: str = ""
    brand_privacy_url: str = ""
    brand_imprint_url: str = ""
    brand_contact_email: str = ""
    brand_contact_phone: str = ""
    #: Extra footer links as "Label|https://url;Label|https://url".
    brand_footer_links: str = ""
    #: Letters scattered as decoration behind the public hero. Empty = none.
    brand_hero_letters: str = ""
    #: Base colours as hex. Each becomes a full 50-900 scale at runtime, so a
    #: re-brand needs no CSS rebuild.
    brand_color_primary: str = "#3b4a6b"
    brand_color_accent: str = "#f0b429"
    brand_color_highlight: str = "#5b3a7a"
    brand_color_surface: str = "#f8fafc"
    brand_color_footer: str = "#1e293b"
    brand_font_heading: str = "Inter"
    brand_font_body: str = "Inter"
    #: Optional stylesheet that loads the fonts named above.
    brand_font_css_url: str = ""

    # --- member booking policy ---
    #: Without these, any account holder could block a room for a year
    #: unsupervised, since internal bookings are instant-confirm.
    member_booking_max_horizon_days: int = 90
    member_booking_max_duration_hours: int = 12

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> list[str]:
        if value is None or value == "":
            return []
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return []

    @field_validator(
        "supported_languages",
        "babel_translation_directories",
        "mail_admin_recipients",
        mode="before",
    )
    @classmethod
    def parse_csv_list(cls, value: object) -> list[str]:
        if value is None or value == "":
            return []
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return []

    @field_validator("default_language", mode="before")
    @classmethod
    def parse_default_language(cls, value: object) -> str:
        if not value:
            return "de"
        return str(value).strip().lower()


@lru_cache
def get_settings() -> Settings:
    return Settings()
