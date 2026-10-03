from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AuditActorRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    display_name: str
    email: str


class AuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    entity_type: str
    entity_id: int | None
    action: str
    actor: AuditActorRead | None
    before_json: dict | None
    after_json: dict | None


class AuditLogPage(BaseModel):
    items: list[AuditLogRead]
    total: int
    page: int
    page_size: int
