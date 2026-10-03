from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class AuditLogRead(ORMModel):
    id: int
    entity_type: str
    entity_id: int
    action: str
    actor_user_id: int | None
    before_json: dict | None
    after_json: dict | None
    created_at: datetime

