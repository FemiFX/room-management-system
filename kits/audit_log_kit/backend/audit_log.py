from datetime import datetime
from models import db

class AuditLog(db.Model):
    """Audit log for tracking all system actions"""
    __tablename__ = 'audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)

    # Action details
    action = db.Column(db.String(100), nullable=False, index=True)  # login, view_application, approve, reject, etc.
    resource_type = db.Column(db.String(50), index=True)  # application, user, document, payment, etc.
    resource_id = db.Column(db.Integer, index=True)  # ID of the resource

    # Additional context
    details = db.Column(db.JSON)  # Store additional details as JSON
    ip_address = db.Column(db.String(45))  # IPv4 or IPv6
    user_agent = db.Column(db.String(255))

    # Timestamp
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Relationships
    user = db.relationship('User', back_populates='audit_logs')

    def __repr__(self):
        return f'<AuditLog {self.action} by User {self.user_id} at {self.created_at}>'

    @property
    def time_ago(self):
        """Return human-readable time difference"""
        now = datetime.utcnow()
        diff = now - self.created_at

        if diff.days > 365:
            years = diff.days // 365
            return f'vor {years} Jahr{"en" if years > 1 else ""}'
        elif diff.days > 30:
            months = diff.days // 30
            return f'vor {months} Monat{"en" if months > 1 else ""}'
        elif diff.days > 0:
            return f'vor {diff.days} Tag{"en" if diff.days > 1 else ""}'
        elif diff.seconds > 3600:
            hours = diff.seconds // 3600
            return f'vor {hours} Stunde{"n" if hours > 1 else ""}'
        elif diff.seconds > 60:
            minutes = diff.seconds // 60
            return f'vor {minutes} Minute{"n" if minutes > 1 else ""}'
        else:
            return 'gerade eben'

    @property
    def description(self):
        """Return human-readable description of the action"""
        if self.details:
            if self.action == 'change_application_status':
                old_status = self.details.get('old_status', '')
                new_status = self.details.get('new_status', '')
                app_id = f" (Antrag #{self.resource_id})" if self.resource_id else ""
                return f"Status geändert von {old_status} zu {new_status}{app_id}"
            elif self.action == 'review_application':
                decision = self.details.get('decision', '')
                amount = self.details.get('approved_amount')
                if amount:
                    return f"Review: {decision} (€{amount})"
                return f"Review: {decision}"
            elif self.action == 'application_submitted':
                ref = self.details.get('reference_number', '')
                return f"Neuer Antrag eingereicht (Ref: {ref})"
            elif self.action == 'user_created':
                email = self.details.get('email', '')
                return f"Neuer Benutzer erstellt: {email}" if email else 'Neuer Benutzer erstellt'
            elif self.action == 'user_updated':
                email = self.details.get('email', '')
                return f"Benutzer aktualisiert: {email}" if email else 'Benutzer aktualisiert'

        action_descriptions = {
            'login': 'Benutzer angemeldet',
            'logout': 'Benutzer abgemeldet',
            'view_application': 'Antrag angesehen',
            'user_created': 'Neuer Benutzer erstellt',
            'user_updated': 'Benutzer aktualisiert',
            'user_deleted': 'Benutzer gelöscht',
        }

        return action_descriptions.get(self.action, self.action.replace('_', ' ').title())

    @property
    def timestamp(self):
        """Alias for created_at to maintain compatibility"""
        return self.created_at

    @staticmethod
    def log_action(user_id, action, resource_type=None, resource_id=None,
                   details=None, ip_address=None, user_agent=None):
        """Create audit log entry"""
        log_entry = AuditLog(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            ip_address=ip_address,
            user_agent=user_agent
        )
        db.session.add(log_entry)
        return log_entry

    @staticmethod
    def log_login(user, ip_address=None, user_agent=None):
        """Log user login"""
        return AuditLog.log_action(
            user_id=user.id,
            action='login',
            ip_address=ip_address,
            user_agent=user_agent
        )

    @staticmethod
    def log_logout(user, ip_address=None, user_agent=None):
        """Log user logout"""
        return AuditLog.log_action(
            user_id=user.id,
            action='logout',
            ip_address=ip_address,
            user_agent=user_agent
        )

    @staticmethod
    def log_application_view(user, application_id):
        """Log application view"""
        return AuditLog.log_action(
            user_id=user.id,
            action='view_application',
            resource_type='application',
            resource_id=application_id
        )

    @staticmethod
    def log_application_status_change(user, application_id, old_status, new_status):
        """Log application status change"""
        return AuditLog.log_action(
            user_id=user.id,
            action='change_application_status',
            resource_type='application',
            resource_id=application_id,
            details={
                'old_status': old_status,
                'new_status': new_status
            }
        )

    @staticmethod
    def log_review_decision(user, application_id, decision, amount=None):
        """Log review decision"""
        return AuditLog.log_action(
            user_id=user.id,
            action='review_application',
            resource_type='application',
            resource_id=application_id,
            details={
                'decision': decision,
                'approved_amount': str(amount) if amount else None
            }
        )

    @staticmethod
    def log_payment_action(user, payment_id, action, details=None):
        """Log payment action"""
        return AuditLog.log_action(
            user_id=user.id,
            action=f'payment_{action}',
            resource_type='payment',
            resource_id=payment_id,
            details=details
        )

    @staticmethod
    def log_application_submitted(application, ip_address=None, user_agent=None):
        """Log application submission (public submission without user account)"""
        log_entry = AuditLog(
            user_id=None,  # Public submission, no user ID
            action='application_submitted',
            resource_type='application',
            resource_id=application.id,
            details={
                'reference_number': application.reference_number,
                'email': application.email
            },
            ip_address=ip_address,
            user_agent=user_agent
        )
        db.session.add(log_entry)
        return log_entry
