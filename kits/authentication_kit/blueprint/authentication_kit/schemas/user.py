from datetime import datetime

from pydantic import BaseModel, EmailStr

from authentication_kit.models.enums import Role
from authentication_kit.schemas.common import ORMModel


class UserRead(ORMModel):
    id: int
    email: EmailStr | None
    display_name: str
    role: Role
    is_active: bool
    last_login_at: datetime | None


class UserRoleUpdate(BaseModel):
    role: Role


class UserActiveUpdate(BaseModel):
    is_active: bool

