from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import distinct, func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.api.deps import require_role
from app.db.session import get_db
from app.models.audit_log import AuditLog
from app.models.enums import Role
from app.models.user import User
from app.schemas.audit import AuditActorRead, AuditLogPage, AuditLogRead

CSV_ROW_LIMIT = 50_000

router = APIRouter(prefix="/admin/audit-logs", tags=["admin-audit-logs"])


SortOption = Literal["created_at_desc", "created_at_asc"]


def _serialize(row: AuditLog) -> AuditLogRead:
    actor = (
        AuditActorRead(id=row.actor.id, display_name=row.actor.display_name, email=row.actor.email)
        if row.actor is not None
        else None
    )
    return AuditLogRead(
        id=row.id,
        created_at=row.created_at,
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        action=row.action,
        actor=actor,
        before_json=row.before_json,
        after_json=row.after_json,
    )


def _build_filtered_query(
    *,
    entity_type: str | None,
    action: str | None,
    actor_user_id: int | None,
    date_from: date | None,
    date_to: date | None,
    q: str | None,
):
    stmt = select(AuditLog).join(User, AuditLog.actor_user_id == User.id, isouter=True)

    conditions = []
    if entity_type:
        conditions.append(AuditLog.entity_type == entity_type)
    if action:
        conditions.append(AuditLog.action == action)
    if actor_user_id is not None:
        conditions.append(AuditLog.actor_user_id == actor_user_id)
    if date_from is not None:
        conditions.append(AuditLog.created_at >= datetime.combine(date_from, time.min, tzinfo=timezone.utc))
    if date_to is not None:
        end_exclusive = datetime.combine(date_to, time.min, tzinfo=timezone.utc) + timedelta(days=1)
        conditions.append(AuditLog.created_at < end_exclusive)
    if q:
        like = f"%{q.strip()}%"
        conditions.append(
            or_(
                AuditLog.entity_type.ilike(like),
                AuditLog.action.ilike(like),
                User.display_name.ilike(like),
                User.email.ilike(like),
            )
        )
    if conditions:
        stmt = stmt.where(*conditions)
    return stmt


@router.get("", response_model=AuditLogPage)
def list_audit_logs(
    entity_type: str | None = Query(default=None),
    action: str | None = Query(default=None),
    actor_user_id: int | None = Query(default=None),
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    q: str | None = Query(default=None),
    sort: SortOption = Query(default="created_at_desc"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    _: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN)),
    db: Session = Depends(get_db),
) -> AuditLogPage:
    stmt = _build_filtered_query(
        entity_type=entity_type,
        action=action,
        actor_user_id=actor_user_id,
        date_from=date_from,
        date_to=date_to,
        q=q,
    )

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0

    if sort == "created_at_asc":
        stmt = stmt.order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
    else:
        stmt = stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())

    stmt = stmt.options(joinedload(AuditLog.actor)).offset((page - 1) * page_size).limit(page_size)

    rows = list(db.scalars(stmt).all())
    return AuditLogPage(
        items=[_serialize(row) for row in rows],
        total=int(total),
        page=page,
        page_size=page_size,
    )


@router.get(".csv")
def export_audit_logs_csv(
    entity_type: str | None = Query(default=None),
    action: str | None = Query(default=None),
    actor_user_id: int | None = Query(default=None),
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    q: str | None = Query(default=None),
    sort: SortOption = Query(default="created_at_desc"),
    _: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN)),
    db: Session = Depends(get_db),
):
    stmt = _build_filtered_query(
        entity_type=entity_type,
        action=action,
        actor_user_id=actor_user_id,
        date_from=date_from,
        date_to=date_to,
        q=q,
    )
    if sort == "created_at_asc":
        stmt = stmt.order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
    else:
        stmt = stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
    stmt = stmt.options(joinedload(AuditLog.actor)).limit(CSV_ROW_LIMIT)

    rows = list(db.scalars(stmt).all())

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "timestamp", "actor_email", "actor_display_name",
        "entity_type", "entity_id", "action", "before_json", "after_json",
    ])
    for row in rows:
        writer.writerow([
            row.created_at.isoformat() if row.created_at else "",
            row.actor.email if row.actor else "",
            row.actor.display_name if row.actor else "",
            row.entity_type,
            row.entity_id if row.entity_id is not None else "",
            row.action,
            json.dumps(row.before_json, ensure_ascii=False) if row.before_json is not None else "",
            json.dumps(row.after_json, ensure_ascii=False) if row.after_json is not None else "",
        ])

    buffer.seek(0)
    filename = f"audit-log-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.csv"
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/facets")
def audit_log_facets(
    _: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN)),
    db: Session = Depends(get_db),
):
    """Distinct values to populate the admin filter dropdowns."""
    entity_types = list(db.scalars(select(distinct(AuditLog.entity_type)).order_by(AuditLog.entity_type)).all())
    actions = list(db.scalars(select(distinct(AuditLog.action)).order_by(AuditLog.action)).all())
    actor_ids = list(
        db.scalars(
            select(distinct(AuditLog.actor_user_id)).where(AuditLog.actor_user_id.is_not(None))
        ).all()
    )
    actors = []
    if actor_ids:
        users = list(db.scalars(select(User).where(User.id.in_(actor_ids)).order_by(User.display_name)).all())
        actors = [
            {"id": u.id, "display_name": u.display_name, "email": u.email} for u in users
        ]
    return {
        "entity_types": entity_types,
        "actions": actions,
        "actors": actors,
    }
