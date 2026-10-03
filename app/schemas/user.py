from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr

from app.models.enums import Role
from app.schemas.common import ORMModel


class UserCreate(BaseModel):
    email: EmailStr
    display_name: str
    role: Role = Role.VIEWER
    preferred_language: str = "de"
    is_active: bool = True


class UserUpdate(BaseModel):
    display_name: str | None = None
    role: Role | None = None
    preferred_language: str | None = None
    is_active: bool | None = None


class UserRead(ORMModel):
    id: int
    email: EmailStr
    display_name: str
    role: Role
    preferred_language: str
    is_active: bool
    oidc_subject: str | None
    oidc_issuer: str | None
    last_login_at: datetime | None


class MeRead(UserRead):
    csrf_token: str
