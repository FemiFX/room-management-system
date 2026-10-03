"""
Audit log routes for admin users.
"""
from datetime import datetime
import csv
from io import StringIO, BytesIO

from flask import Blueprint, render_template, request, make_response, jsonify
from flask_login import current_user
from sqlalchemy import desc, asc
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

from models import db, AuditLog, User
from utils.decorators import admin_required

admin_audit_bp = Blueprint('admin_audit', __name__, url_prefix='/admin')


@admin_audit_bp.route('/audit', methods=['GET'])
@admin_required
def audit():
    """Audit log viewer with pagination, sorting, and filtering."""
    action_filter = request.args.get('action')
    user_filter = request.args.get('user_id', type=int)
    sort_order = request.args.get('sort', 'desc')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)

    query = AuditLog.query
    if action_filter:
        query = query.filter(AuditLog.action == action_filter)
    if user_filter:
        query = query.filter(AuditLog.user_id == user_filter)

    if sort_order == 'asc':
        query = query.order_by(asc(AuditLog.created_at))
    else:
        query = query.order_by(desc(AuditLog.created_at))

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    logs = pagination.items

    users = User.query.order_by(User.email.asc()).all()
    actions = [row[0] for row in db.session.query(AuditLog.action).distinct().order_by(AuditLog.action).all()]

    return render_template(
        'backend/admin_audit.html',
        logs=logs,
        pagination=pagination,
        users=users,
        actions=actions,
        selected_action=action_filter,
        selected_user=user_filter,
        sort_order=sort_order,
        per_page=per_page,
        user_name=current_user.full_name,
        user_initials=current_user.initials,
        user_role=current_user.role.value.replace('_', ' ').title(),
    )


@admin_audit_bp.route('/audit/data', methods=['GET'])
@admin_required
def audit_data():
    """AJAX endpoint for audit log data (sorting/pagination)."""
    action_filter = request.args.get('action')
    user_filter = request.args.get('user_id', type=int)
    sort_order = request.args.get('sort', 'desc')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)

    query = AuditLog.query
    if action_filter:
        query = query.filter(AuditLog.action == action_filter)
    if user_filter:
        query = query.filter(AuditLog.user_id == user_filter)

    if sort_order == 'asc':
        query = query.order_by(asc(AuditLog.created_at))
    else:
        query = query.order_by(desc(AuditLog.created_at))

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    logs = pagination.items

    logs_data = []
    for log in logs:
        logs_data.append({
            'id': log.id,
            'created_at': log.created_at.strftime('%d.%m.%Y %H:%M:%S') if log.created_at else '',
            'created_at_date': log.created_at.strftime('%d.%m.%Y') if log.created_at else '—',
            'created_at_time': log.created_at.strftime('%H:%M:%S') if log.created_at else '',
            'user_initials': log.user.initials if log.user else 'SYS',
            'user_name': log.user.full_name if log.user else 'System',
            'user_email': log.user.email if log.user else 'Automatisch',
            'action': log.action,
            'action_display': log.action.replace('_', ' ').title(),
            'resource_type': log.resource_type if log.resource_type else None,
            'resource_id': log.resource_id if log.resource_id else None,
            'ip_address': log.ip_address if log.ip_address else '—',
            'description': log.description if log.description else '—',
        })

    return jsonify({
        'logs': logs_data,
        'pagination': {
            'page': pagination.page,
            'pages': pagination.pages,
            'total': pagination.total,
            'per_page': pagination.per_page,
            'has_prev': pagination.has_prev,
            'has_next': pagination.has_next,
            'prev_num': pagination.prev_num,
            'next_num': pagination.next_num,
        },
        'sort_order': sort_order,
    })


@admin_audit_bp.route('/audit/export/csv', methods=['GET'])
@admin_required
def audit_export_csv():
    """Export audit logs as CSV."""
    action_filter = request.args.get('action')
    user_filter = request.args.get('user_id', type=int)
    sort_order = request.args.get('sort', 'desc')

    query = AuditLog.query
    if action_filter:
        query = query.filter(AuditLog.action == action_filter)
    if user_filter:
        query = query.filter(AuditLog.user_id == user_filter)

    if sort_order == 'asc':
        query = query.order_by(asc(AuditLog.created_at))
    else:
        query = query.order_by(desc(AuditLog.created_at))

    logs = query.all()

    si = StringIO()
    writer = csv.writer(si)
    writer.writerow(['Zeitstempel', 'Benutzer', 'Aktion', 'Ressourcentyp', 'Ressourcen-ID', 'IP-Adresse', 'Beschreibung'])

    for log in logs:
        writer.writerow([
            log.created_at.strftime('%d.%m.%Y %H:%M:%S') if log.created_at else '',
            log.user.email if log.user else 'System',
            log.action,
            log.resource_type if log.resource_type else '—',
            log.resource_id if log.resource_id else '—',
            log.ip_address if log.ip_address else '—',
            log.description
        ])

    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = f"attachment; filename=audit_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    output.headers["Content-type"] = "text/csv"
    return output


@admin_audit_bp.route('/audit/export/pdf', methods=['GET'])
@admin_required
def audit_export_pdf():
    """Export audit logs as PDF."""
    action_filter = request.args.get('action')
    user_filter = request.args.get('user_id', type=int)
    sort_order = request.args.get('sort', 'desc')

    query = AuditLog.query
    if action_filter:
        query = query.filter(AuditLog.action == action_filter)
    if user_filter:
        query = query.filter(AuditLog.user_id == user_filter)

    if sort_order == 'asc':
        query = query.order_by(asc(AuditLog.created_at))
    else:
        query = query.order_by(desc(AuditLog.created_at))

    logs = query.limit(1000).all()

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=30,
        leftMargin=30,
        topMargin=30,
        bottomMargin=18
    )
    elements = []

    styles = getSampleStyleSheet()
    title = Paragraph("Audit Logs", styles['Heading1'])
    elements.append(title)
    elements.append(Spacer(1, 12))

    date_text = Paragraph(f"Generiert: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}", styles['Normal'])
    elements.append(date_text)
    elements.append(Spacer(1, 12))

    body_style = styles['BodyText']
    body_style.fontSize = 8
    body_style.leading = 10

    header = ['Zeit', 'Benutzer', 'Aktion', 'Ressource', 'Beschreibung']
    data = [header]
    for log in logs:
        data.append([
            Paragraph(log.created_at.strftime('%d.%m.%Y %H:%M') if log.created_at else '', body_style),
            Paragraph(log.user.email if log.user else 'System', body_style),
            Paragraph(log.action or '—', body_style),
            Paragraph(f"{log.resource_type or '—'} #{log.resource_id or '—'}", body_style),
            Paragraph(log.description or '—', body_style),
        ])

    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 11),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))

    elements.append(table)
    doc.build(elements)

    buffer.seek(0)
    response = make_response(buffer.getvalue())
    response.headers["Content-Disposition"] = f"attachment; filename=audit_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    response.headers["Content-Type"] = "application/pdf"
    return response
