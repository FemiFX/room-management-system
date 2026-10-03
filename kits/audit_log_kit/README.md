# Audit Log Kit

Drop-in audit logging model, admin routes, and UI template for viewing, filtering, sorting, and exporting audit logs.

## What's inside
- `backend/audit_log.py` - SQLAlchemy model with helper logging methods and computed fields.
- `backend/audit_routes.py` - admin routes for list view, AJAX data, CSV export, and PDF export.
- `templates/backend/admin_audit.html` - full admin audit log page with filters, table, export dropdown, and JS.

## Expected context (template)
The audit page expects these context values:
- `logs`: list of `AuditLog` rows
- `pagination`: SQLAlchemy pagination object
- `users`: list of users for filter dropdown
- `actions`: list of distinct action strings
- `selected_action`, `selected_user`, `sort_order`, `per_page`
- `user_name`, `user_initials`, `user_role` (used by `base_admin.html`)

## Endpoints expected by the JS
- `GET /admin/audit/data` (JSON data for sorting/pagination)
- `GET /admin/audit/export/csv`
- `GET /admin/audit/export/pdf`

The template assumes the `/admin/audit` page is the main route.

## Backend wiring (Flask)
Register the audit blueprint from `backend/audit_routes.py`:

```python
from audit_log_kit.backend.audit_routes import admin_audit_bp
app.register_blueprint(admin_audit_bp)
```

If you already have an admin tools blueprint, you can move the route functions into it instead.

## Model setup
The `AuditLog` model in `backend/audit_log.py` is identical to `models/audit_log.py` in this repo. If you reuse this kit elsewhere, add a migration for the `audit_logs` table (see `migrations/versions/e97739198dd1_initial_database_schema.py`).

## Logging examples
```python
from flask import request
from flask_login import current_user
from models import AuditLog
from utils.helpers import get_client_ip

AuditLog.log_action(
    user_id=current_user.id,
    action='update_settings',
    resource_type='settings',
    details={'REVIEWS_REQUIRED': 3},
    ip_address=get_client_ip(),
    user_agent=request.user_agent.string
)
```

## Notes
- The audit page extends `backend/base_admin.html` and uses the Tailwind palette defined in this repo.
- PDF export depends on `reportlab` (already in `requirements.txt`).
- IP address extraction uses `utils/helpers.py:get_client_ip()`.
