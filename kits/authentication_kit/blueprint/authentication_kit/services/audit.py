from __future__ import annotations

from sqlalchemy.orm import Session

from authentication_kit.models.audit_log import AuditLog


def create_audit_entry(
    db: Session,
    *,
    entity_type: str,
    entity_id: int,
    action: str,
    actor_user_id: int | None,
    before_json: dict | None,
    after_json: dict | None,
) -> AuditLog:
    entry = AuditLog(
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        actor_user_id=actor_user_id,
        before_json=before_json,
        after_json=after_json,
    )
    db.add(entry)
    return entry

