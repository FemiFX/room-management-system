from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog


def create_audit_entry(
    db: Session,
    *,
    entity_type: str,
    entity_id: int | None,
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


def audit(
    db: Session,
    *,
    entity: Any,
    action: str,
    actor_user_id: int | None,
    entity_id: int | None = None,
    before: dict | None = None,
    after: dict | None = None,
) -> AuditLog:
    """Convenience wrapper around create_audit_entry.

    `entity` may be a string (used directly as entity_type) or an ORM row
    (entity_type is inferred from the class name and entity_id from row.id
    when not explicitly provided).
    """
    if isinstance(entity, str):
        entity_type = entity
    else:
        entity_type = entity.__class__.__name__.lower()
        if entity_id is None:
            entity_id = getattr(entity, "id", None)
    return create_audit_entry(
        db,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        actor_user_id=actor_user_id,
        before_json=before,
        after_json=after,
    )
