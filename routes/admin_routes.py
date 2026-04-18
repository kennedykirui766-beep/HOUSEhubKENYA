from flask import Blueprint, render_template, render_template_string, redirect, request, url_for, flash, session, current_app
from flask_login import login_required, current_user, login_user, logout_user
from sqlalchemy import inspect
from sqlalchemy import or_
import logging
import json
import time
import secrets
from models.models import User, House, SystemUpdateSubscriber, SystemSetting
from models.models import EmailTemplate, EmailTemplateVersion, EmailTemplateSendLog
from models.models import SupportTicket, SupportMessage, MaintenanceRequest, Payment, MaintenanceComment
from models.models import AuditLog
from extensions import db, csrf
from flask import make_response
import csv
import io
from datetime import datetime, timedelta
from utils_delete import delete_user_and_dependents

logger = logging.getLogger(__name__)
from utils_email_2fa import send_system_update_email
from utils_email_2fa import send_templated_email
from services.notification import enqueue_system_update_email
from utils_security import (
    clear_admin_totp_verification,
    consume_rate_limit,
    get_request_ip,
    get_allowed_admin_email,
    has_admin_totp_verified,
    is_admin_ip_allowed,
    is_approved_admin,
)

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

SIGNUP_ROLE_CHOICES = ('tenant', 'landlord', 'service')

DEFAULT_EMAIL_TEMPLATES = [
    {
        'key': 'welcome_email',
        'name': 'Welcome Email',
        'category': 'account',
        'description': 'Sent when a new account is created.',
        'subject': 'Welcome to HomeHub, {{ name }}',
        'html_body': '<p>Hello {{ name }},</p><p>Welcome to HomeHub. Your account is ready.</p>',
        'text_body': 'Hello {{ name }},\n\nWelcome to HomeHub. Your account is ready.',
        'variables': ['name', 'email'],
    },
    {
        'key': 'password_reset',
        'name': 'Password Reset',
        'category': 'security',
        'description': 'Used for password reset links.',
        'subject': 'Reset your HomeHub password',
        'html_body': '<p>Hello {{ name }},</p><p>Use this link to reset your password: {{ reset_url }}</p>',
        'text_body': 'Hello {{ name }},\n\nUse this link to reset your password: {{ reset_url }}',
        'variables': ['name', 'reset_url', 'expires_minutes'],
    },
    {
        'key': 'system_update',
        'name': 'System Update',
        'category': 'notifications',
        'description': 'Platform announcements and release notes.',
        'subject': 'HomeHub system update',
        'html_body': '<p>Hello {{ name }},</p><p>{{ body }}</p>',
        'text_body': 'Hello {{ name }},\n\n{{ body }}',
        'variables': ['name', 'body'],
    },
    {
        'key': 'support_contact',
        'name': 'Support Contact',
        'category': 'support',
        'description': 'Inbound contact form notifications sent to support.',
        'subject': 'HomeHub Contact Message from {{ full_name }}',
        'html_body': '<p><strong>Name:</strong> {{ full_name }}</p><p><strong>Email:</strong> {{ sender_email }}</p><p><strong>Phone:</strong> {{ phone or "Not provided" }}</p><p><strong>Role:</strong> {{ role or "Not provided" }}</p><hr><p style="white-space: pre-wrap;">{{ message }}</p>',
        'text_body': 'Name: {{ full_name }}\nEmail: {{ sender_email }}\nPhone: {{ phone or "Not provided" }}\nRole: {{ role or "Not provided" }}\n\nMessage:\n{{ message }}',
        'variables': ['full_name', 'sender_email', 'phone', 'role', 'message'],
    },
]


def _parse_signup_roles(raw_value):
    roles = []
    for item in (raw_value or '').split(','):
        role = item.strip().lower()
        if role in SIGNUP_ROLE_CHOICES and role not in roles:
            roles.append(role)
    return roles


def _ensure_default_email_templates():
    if not inspect(db.engine).has_table('email_template'):
        db.create_all()

    if EmailTemplate.query.count() > 0:
        return

    for template_data in DEFAULT_EMAIL_TEMPLATES:
        template = EmailTemplate(
            key=template_data['key'],
            name=template_data['name'],
            category=template_data['category'],
            description=template_data['description'],
            subject=template_data['subject'],
            html_body=template_data['html_body'],
            text_body=template_data['text_body'],
            is_active=True,
            is_default=True,
        )
        template.set_variables(template_data['variables'])
        db.session.add(template)

    db.session.commit()


def _snapshot_email_template(template, *, created_by_id=None, change_notes=None):
    latest_version = (
        EmailTemplateVersion.query.filter_by(template_id=template.id)
        .order_by(EmailTemplateVersion.version_number.desc())
        .first()
    )
    next_version = 1 if latest_version is None else latest_version.version_number + 1

    version = EmailTemplateVersion(
        template_id=template.id,
        version_number=next_version,
        subject=template.subject,
        html_body=template.html_body,
        text_body=template.text_body,
        change_notes=change_notes,
        created_by_id=created_by_id,
    )
    version.set_variables(template.get_variables())
    db.session.add(version)


def _template_preview_context(template):
    template_key = (template.key or '').lower()
    if template_key == 'password_reset':
        return {
            'name': 'Admin User',
            'email': 'admin@example.com',
            'reset_url': 'https://example.com/reset-password/token',
            'expires_minutes': 60,
        }
    if template_key == 'system_update':
        return {
            'name': 'Admin User',
            'body': 'This is a preview of a platform announcement.',
        }
    if template_key == 'support_contact':
        return {
            'full_name': 'Jane Doe',
            'sender_email': 'jane@example.com',
            'phone': '+254700000000',
            'role': 'tenant',
            'message': 'I need help with my latest invoice.',
        }
    return {
        'name': 'Admin User',
        'email': 'admin@example.com',
    }


def _render_email_preview(template, preview_context):
    if not template:
        return {'subject': '', 'html_body': '', 'text_body': ''}

    return {
        'subject': render_template_string(template.subject or '', **preview_context),
        'html_body': render_template_string(template.html_body or '', **preview_context),
        'text_body': render_template_string(template.text_body or '', **preview_context) if template.text_body else '',
    }


def _restore_email_template_version(template, version, *, actor_user_id=None):
    _snapshot_email_template(
        template,
        created_by_id=actor_user_id,
        change_notes=f'Restored from version {version.version_number}',
    )
    template.subject = version.subject
    template.html_body = version.html_body
    template.text_body = version.text_body
    template.set_variables(version.get_variables())


def _template_version_label(version):
    return f'v{version.version_number}'

# --- Helpers ---
def is_admin():
    return current_user.is_authenticated and is_approved_admin(current_user)


def log_admin_action(action, *, category='admin', target_type=None, target_id=None, status='success', details=None, actor_user_id=None, actor_email=None):
    """Best-effort append-only audit logging for privileged operations."""
    try:
        # Keep feature functional if migrations are temporarily out of sync.
        if not inspect(db.engine).has_table('audit_log'):
            db.create_all()

        payload = None
        if details is not None:
            payload = json.dumps(details, default=str)

        event = AuditLog(
            actor_user_id=actor_user_id if actor_user_id is not None else getattr(current_user, 'id', None),
            actor_email=actor_email if actor_email is not None else getattr(current_user, 'email', None),
            category=(category or 'admin')[:50],
            action=(action or 'unknown_action')[:120],
            target_type=(target_type or '')[:80] or None,
            target_id=str(target_id)[:64] if target_id is not None else None,
            status=(status or 'success')[:20],
            ip_address=(request.headers.get('X-Forwarded-For') or request.remote_addr or '')[:64] or None,
            user_agent=(request.headers.get('User-Agent') or '')[:255] or None,
            details_json=payload,
        )
        db.session.add(event)
        db.session.commit()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        logger.exception('Failed to write audit log')

@admin_bp.before_request
def restrict_to_admin():
    if not session.get('admin_entry_granted'):
        flash("Use the private admin access link before opening admin pages.", "warning")
        return redirect(url_for('auth.semantic_admin_entry'))

    if not is_admin():
        flash("Access denied. Admins only.", "danger")
        return redirect(url_for('auth.login'))

    # Enforce admin IP allowlist (if configured).
    client_ip = get_request_ip()
    if not is_admin_ip_allowed(client_ip):
        log_admin_action(
            'admin_ip_allowlist_block',
            category='security',
            target_type='session',
            target_id=getattr(current_user, 'id', None),
            status='blocked',
            details={'ip': client_ip}
        )
        clear_admin_totp_verification()
        session.pop('admin_entry_granted', None)
        session.pop('admin_entry_granted_at', None)
        session.pop('admin_last_seen_at', None)
        session.pop('admin_session_nonce', None)
        session.pop('admin_id', None)
        session.pop('is_impersonating', None)
        logout_user()
        flash('Admin access from this IP is not allowed.', 'danger')
        return redirect(url_for('auth.login'))

    # Validate server-side admin session nonce so revoke action can invalidate active sessions.
    current_nonce = SystemSetting.get('admin_session_nonce', '')
    if not current_nonce:
        current_nonce = secrets.token_hex(16)
        SystemSetting.set('admin_session_nonce', current_nonce)

    session_nonce = session.get('admin_session_nonce')
    if not session_nonce:
        session['admin_session_nonce'] = current_nonce
        session.modified = True
    elif session_nonce != current_nonce:
        log_admin_action(
            'admin_session_revoked',
            category='security',
            target_type='session',
            target_id=getattr(current_user, 'id', None),
            status='blocked',
            details={'reason': 'nonce_mismatch'}
        )
        clear_admin_totp_verification()
        session.pop('admin_entry_granted', None)
        session.pop('admin_entry_granted_at', None)
        session.pop('admin_last_seen_at', None)
        session.pop('admin_session_nonce', None)
        session.pop('admin_id', None)
        session.pop('is_impersonating', None)
        logout_user()
        flash('Your admin session was revoked. Please sign in again.', 'warning')
        return redirect(url_for('auth.login'))

    # Enforce admin idle timeout (default: 1 hour)
    timeout_seconds = int(current_app.config.get('ADMIN_SESSION_TIMEOUT_SECONDS', 3600) or 3600)
    now_ts = int(time.time())
    last_seen = session.get('admin_last_seen_at')
    if last_seen is not None:
        try:
            if now_ts - int(last_seen) > timeout_seconds:
                log_admin_action(
                    'admin_session_timeout',
                    category='security',
                    target_type='session',
                    target_id=getattr(current_user, 'id', None),
                    details={'idle_seconds': now_ts - int(last_seen), 'timeout_seconds': timeout_seconds}
                )
                clear_admin_totp_verification()
                session.pop('admin_entry_granted', None)
                session.pop('admin_entry_granted_at', None)
                session.pop('admin_last_seen_at', None)
                session.pop('admin_id', None)
                session.pop('is_impersonating', None)
                logout_user()
                flash('Admin session expired after 1 hour of inactivity. Please sign in again.', 'warning')
                return redirect(url_for('auth.login'))
        except Exception:
            # If parsing fails, reset timer safely
            session.pop('admin_last_seen_at', None)

    session['admin_last_seen_at'] = now_ts
    session.modified = True

    if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'}:
        allowed, retry_after = consume_rate_limit(f"admin-post:{current_user.id}:{request.endpoint}", 12, 60)
        if not allowed:
            flash(f"Too many admin actions. Please wait {retry_after}s and try again.", 'warning')
            return redirect(url_for('admin.dashboard'))

    if not current_user.two_factor_enabled or not current_user.two_factor_secret:
        flash("Enable authenticator 2FA before using the admin area.", "warning")
        return redirect(url_for('auth.admin_security_setup'))

    if not has_admin_totp_verified(current_user):
        return redirect(url_for('auth.admin_2fa_verify'))

def get_stats():
    """Return a consistent stats dictionary for all admin pages."""
    # Build last 6-month label window first so chart payload is always present.
    now_utc = datetime.utcnow()
    trend_month_keys = []
    trend_labels = []
    y = now_utc.year
    m = now_utc.month
    for _ in range(6):
        trend_month_keys.append(f"{y:04d}-{m:02d}")
        trend_labels.append(datetime(y, m, 1).strftime('%b %Y'))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    trend_month_keys.reverse()
    trend_labels.reverse()

    payments_trend = {k: 0 for k in trend_month_keys}
    revenue_trend = {k: 0.0 for k in trend_month_keys}
    maintenance_trend = {k: 0 for k in trend_month_keys}
    support_trend = {k: 0 for k in trend_month_keys}

    cutoff_month = datetime.strptime(trend_month_keys[0] + '-01', '%Y-%m-%d')
    # Best-effort derived stats — keep lightweight
    try:
        total_users = User.query.count()
    except Exception:
        total_users = 0

    try:
        total_properties = House.query.count()
    except Exception:
        total_properties = 0

    try:
        occupied_properties = House.query.filter(House.available == False).count()
        vacant_properties = House.query.filter(House.available == True).count()
    except Exception:
        occupied_properties = 0
        vacant_properties = 0

    occupancy_rate = round((occupied_properties / total_properties) * 100, 2) if total_properties else 0.0

    try:
        maintenance_total = MaintenanceRequest.query.count()
        maintenance_open = MaintenanceRequest.query.filter(MaintenanceRequest.status != 'resolved').count()
        maintenance_resolved = MaintenanceRequest.query.filter(MaintenanceRequest.status == 'resolved').count()
        maintenance_pending = MaintenanceRequest.query.filter(MaintenanceRequest.status == 'pending').count()
        maintenance_in_progress = MaintenanceRequest.query.filter(MaintenanceRequest.status == 'in_progress').count()
    except Exception:
        maintenance_total = maintenance_open = maintenance_resolved = 0
        maintenance_pending = maintenance_in_progress = 0

    try:
        support_total = SupportTicket.query.count()
        support_open = SupportTicket.query.filter(SupportTicket.status != 'resolved').count()
        support_resolved = SupportTicket.query.filter(SupportTicket.status == 'resolved').count()
        support_escalated = SupportTicket.query.filter(SupportTicket.status == 'escalated').count()
    except Exception:
        support_total = 0
        support_open = 0
        support_resolved = 0
        support_escalated = 0

    # Payment totals and trends
    try:
        total_transactions = Payment.query.count()
    except Exception:
        total_transactions = 0

    try:
        payments_paid = Payment.query.filter(
            (Payment.status.ilike('%paid%')) |
            (Payment.status.ilike('%success%')) |
            (Payment.status.ilike('%complete%'))
        ).all()
        paid_amount_total = round(sum(float(p.amount or 0) for p in payments_paid), 2)
        payments_paid_count = len(payments_paid)
    except Exception:
        paid_amount_total = 0.0
        payments_paid_count = 0

    try:
        payments_pending_count = Payment.query.filter(Payment.status.ilike('%pending%')).count()
    except Exception:
        payments_pending_count = 0

    # Payment failures heuristic
    try:
        payment_failures = Payment.query.filter(
            (Payment.status.ilike('%fail%')) | (Payment.status.ilike('%error%'))
        ).count()
    except Exception:
        payment_failures = 0

    payment_success_rate = round((payments_paid_count / total_transactions) * 100, 2) if total_transactions else 0.0

    # Month-to-date revenue snapshot based on payment date
    try:
        month_start = now_utc.date().replace(day=1)
        mtd_payments = Payment.query.filter(Payment.date >= month_start).all()
        revenue_mtd = round(sum(float(p.amount or 0) for p in mtd_payments), 2)
        transactions_mtd = len(mtd_payments)
    except Exception:
        revenue_mtd = 0.0
        transactions_mtd = 0

    # Real trend series (last 6 months): payments and revenue
    try:
        trend_payments = Payment.query.filter(Payment.created_at >= cutoff_month).all()
        for p in trend_payments:
            created_at = getattr(p, 'created_at', None)
            if not created_at:
                continue
            key = created_at.strftime('%Y-%m')
            if key not in payments_trend:
                continue
            payments_trend[key] += 1
            status_text = (getattr(p, 'status', '') or '').lower()
            if ('paid' in status_text) or ('success' in status_text) or ('complete' in status_text):
                revenue_trend[key] += float(getattr(p, 'amount', 0) or 0)
    except Exception:
        pass

    # Real trend series (last 6 months): maintenance requests
    try:
        trend_maintenance = MaintenanceRequest.query.filter(MaintenanceRequest.created_at >= cutoff_month).all()
        for req in trend_maintenance:
            created_at = getattr(req, 'created_at', None)
            if not created_at:
                continue
            key = created_at.strftime('%Y-%m')
            if key in maintenance_trend:
                maintenance_trend[key] += 1
    except Exception:
        pass

    # Real trend series (last 6 months): support tickets
    try:
        trend_support = SupportTicket.query.filter(SupportTicket.created_at >= cutoff_month).all()
        for ticket in trend_support:
            created_at = getattr(ticket, 'created_at', None)
            if not created_at:
                continue
            key = created_at.strftime('%Y-%m')
            if key in support_trend:
                support_trend[key] += 1
    except Exception:
        pass

    # Last-30-days operational volume
    cutoff_30d = datetime.utcnow() - timedelta(days=30)
    try:
        payments_30d = Payment.query.filter(Payment.created_at >= cutoff_30d).count()
    except Exception:
        payments_30d = 0

    try:
        maintenance_30d = MaintenanceRequest.query.filter(MaintenanceRequest.created_at >= cutoff_30d).count()
    except Exception:
        maintenance_30d = 0

    try:
        support_30d = SupportTicket.query.filter(SupportTicket.created_at >= cutoff_30d).count()
    except Exception:
        support_30d = 0

    # Role distribution for admin insights
    role_counts = {}
    for role_name in ('tenant', 'landlord', 'service', 'admin'):
        try:
            role_counts[role_name] = User.query.filter(User.role == role_name).count()
        except Exception:
            role_counts[role_name] = 0

    # Background queue length
    queue_len = 0
    try:
        import services.notification as notification
        queue_len = notification._task_queue.qsize()
    except Exception:
        queue_len = 0

    # DB health check
    db_ok = True
    try:
        db.session.execute('SELECT 1')
    except Exception:
        db_ok = False

    return {
        'total_users': total_users,
        'total_properties': total_properties,
        'occupied_properties': occupied_properties,
        'vacant_properties': vacant_properties,
        'occupancy_rate': occupancy_rate,
        'maintenance_total': maintenance_total,
        'maintenance_open': maintenance_open,
        'maintenance_resolved': maintenance_resolved,
        'maintenance_pending': maintenance_pending,
        'maintenance_in_progress': maintenance_in_progress,
        'support_total': support_total,
        'support_open': support_open,
        'support_resolved': support_resolved,
        'support_escalated': support_escalated,
        'total_transactions': total_transactions,
        'payments_paid_count': payments_paid_count,
        'payments_pending_count': payments_pending_count,
        'payment_failures': payment_failures,
        'payment_success_rate': payment_success_rate,
        'paid_amount_total': paid_amount_total,
        'revenue_mtd': revenue_mtd,
        'transactions_mtd': transactions_mtd,
        'payments_30d': payments_30d,
        'maintenance_30d': maintenance_30d,
        'support_30d': support_30d,
        'role_counts': role_counts,
        'trend_labels': trend_labels,
        'payments_trend': [payments_trend[k] for k in trend_month_keys],
        'revenue_trend': [round(revenue_trend[k], 2) for k in trend_month_keys],
        'maintenance_trend': [maintenance_trend[k] for k in trend_month_keys],
        'support_trend': [support_trend[k] for k in trend_month_keys],
        'queue_length': queue_len,
        'db_ok': db_ok,
        'uptime': 99.5,
        'api_response': 280,
    }

# --- Dashboard ---
@admin_bp.route('/dashboard')
@login_required
def dashboard():
    users = User.query.all()
    houses = House.query.all()
    stats = get_stats()
    return render_template(
        'admin.html',
        users=users,
        houses=houses,
        stats=stats,
        approved_admin_email=get_allowed_admin_email(),
        admin_totp_verified=has_admin_totp_verified(current_user),
    )

@admin_bp.route('/system_settings')
@login_required
def system_settings():
    # Redirect to the main platform settings handler which builds the settings context
    return redirect(url_for('admin.platform_settings'))

@admin_bp.route('/manage_users')
@login_required
def manage_users():
    users = User.query.all()
    stats = get_stats()
    return render_template('admin.html', users=users, stats=stats)

@admin_bp.route('/delete_user/<int:user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)

    # Prevent self-deletion
    if current_user.id == user.id:
        flash("You cannot delete your own admin account.", "danger")
        return redirect(url_for('admin.dashboard'))

    # If 'hard' provided, perform full deletion, else soft-deactivate
    hard = request.form.get('confirm') == 'hard'
    if hard:
        success, error = delete_user_and_dependents(user)
        if success:
            logger.info(f"Admin {current_user.id} hard-deleted user {user_id}")
            log_admin_action(
                'user_hard_delete',
                target_type='user',
                target_id=user_id,
                details={'mode': 'hard', 'result': 'deleted'}
            )
            flash("User permanently deleted.", "success")
        else:
            log_admin_action(
                'user_hard_delete',
                target_type='user',
                target_id=user_id,
                status='failed',
                details={'mode': 'hard', 'error': error}
            )
            flash(f"Failed to delete user: {error}", "danger")
    else:
        # Soft-delete / deactivate
        setattr(user, 'is_active', False)
        db.session.commit()
        logger.info(f"Admin {current_user.id} deactivated user {user_id}")
        log_admin_action(
            'user_soft_deactivate',
            target_type='user',
            target_id=user_id,
            details={'mode': 'soft'}
        )
        flash("User deactivated (soft-delete).", "success")

    return redirect(url_for('admin.dashboard'))

# --- Manage Properties ---
@admin_bp.route('/manage_properties')
@login_required
def manage_properties():
    houses = House.query.all()
    stats = get_stats()
    return render_template('admin.html', houses=houses, stats=stats)

@admin_bp.route('/delete_property/<int:house_id>', methods=['POST'])
@login_required
def delete_property(house_id):
    house = House.query.get_or_404(house_id)
    # If 'hard' confirmation provided, delete; otherwise mark unavailable
    hard = request.form.get('confirm') == 'hard'
    if hard:
        db.session.delete(house)
        db.session.commit()
        logger.info(f"Admin {current_user.id} hard-deleted property {house_id}")
        log_admin_action(
            'property_hard_delete',
            target_type='property',
            target_id=house_id,
            details={'mode': 'hard'}
        )
        flash("Property permanently removed.")
    else:
        house.available = False
        db.session.commit()
        logger.info(f"Admin {current_user.id} marked property {house_id} unavailable (soft)")
        log_admin_action(
            'property_soft_disable',
            target_type='property',
            target_id=house_id,
            details={'mode': 'soft', 'available': False}
        )
        flash("Property marked unavailable.")
    return redirect(url_for('admin.dashboard'))

# --- Reports ---
@admin_bp.route('/view_reports')
@login_required
def view_reports():
    stats = get_stats()
    return render_template('admin.view_reports.html', stats=stats)


@admin_bp.route('/audit_logs')
@login_required
def audit_logs():
    # Server-side filtering and export for immutable audit events
    q = (request.args.get('q') or '').strip()
    category = (request.args.get('category') or '').strip()
    action = (request.args.get('action') or '').strip()
    status = (request.args.get('status') or '').strip()
    target_type = (request.args.get('target_type') or '').strip()
    actor_email = (request.args.get('actor_email') or '').strip()
    start_date = (request.args.get('start_date') or '').strip()
    end_date = (request.args.get('end_date') or '').strip()

    page = int(request.args.get('page') or 1)
    per_page = int(request.args.get('per_page') or 25)
    per_page = max(10, min(per_page, 100))

    base = AuditLog.query

    if q:
        like_q = f"%{q}%"
        base = base.filter(
            or_(
                AuditLog.action.ilike(like_q),
                AuditLog.category.ilike(like_q),
                AuditLog.actor_email.ilike(like_q),
                AuditLog.target_type.ilike(like_q),
                AuditLog.target_id.ilike(like_q),
                AuditLog.details_json.ilike(like_q),
            )
        )

    if category:
        base = base.filter(AuditLog.category == category)
    if action:
        base = base.filter(AuditLog.action == action)
    if status:
        base = base.filter(AuditLog.status == status)
    if target_type:
        base = base.filter(AuditLog.target_type == target_type)
    if actor_email:
        base = base.filter(AuditLog.actor_email.ilike(f"%{actor_email}%"))

    try:
        if start_date:
            sd = datetime.fromisoformat(start_date)
            base = base.filter(AuditLog.created_at >= sd)
        if end_date:
            ed = datetime.fromisoformat(end_date)
            base = base.filter(AuditLog.created_at <= ed)
    except Exception:
        pass

    sort_by = (request.args.get('sort_by') or 'created_at').strip()
    sort_dir = (request.args.get('sort_dir') or 'desc').strip().lower()
    order_col = AuditLog.created_at
    if sort_by == 'action':
        order_col = AuditLog.action
    elif sort_by == 'actor_email':
        order_col = AuditLog.actor_email
    elif sort_by == 'status':
        order_col = AuditLog.status

    if sort_dir == 'asc':
        base = base.order_by(order_col.asc())
    else:
        base = base.order_by(order_col.desc())

    export_fmt = (request.args.get('export') or '').strip().lower()
    if export_fmt in ('csv', 'excel'):
        rows = base.all()
        output = io.StringIO()
        writer = csv.writer(output, delimiter='\t' if export_fmt == 'excel' else ',')
        writer.writerow([
            'id', 'created_at', 'category', 'action', 'status',
            'actor_user_id', 'actor_email', 'target_type', 'target_id',
            'ip_address', 'user_agent', 'details_json'
        ])
        for r in rows:
            writer.writerow([
                r.id,
                r.created_at.isoformat() if r.created_at else '',
                r.category,
                r.action,
                r.status,
                r.actor_user_id or '',
                r.actor_email or '',
                r.target_type or '',
                r.target_id or '',
                r.ip_address or '',
                r.user_agent or '',
                r.details_json or '',
            ])

        resp = make_response(output.getvalue())
        if export_fmt == 'excel':
            resp.headers['Content-Type'] = 'application/vnd.ms-excel; charset=utf-8'
            resp.headers['Content-Disposition'] = 'attachment; filename="audit_logs.xls"'
        else:
            resp.headers['Content-Type'] = 'text/csv; charset=utf-8'
            resp.headers['Content-Disposition'] = 'attachment; filename="audit_logs.csv"'
        return resp

    pagination = base.paginate(page=page, per_page=per_page, error_out=False)
    items = pagination.items
    stats = get_stats()

    categories = [v[0] for v in db.session.query(AuditLog.category).distinct().order_by(AuditLog.category.asc()).all() if v and v[0]]
    actions = [v[0] for v in db.session.query(AuditLog.action).distinct().order_by(AuditLog.action.asc()).all() if v and v[0]]
    statuses = [v[0] for v in db.session.query(AuditLog.status).distinct().order_by(AuditLog.status.asc()).all() if v and v[0]]
    target_types = [v[0] for v in db.session.query(AuditLog.target_type).distinct().order_by(AuditLog.target_type.asc()).all() if v and v[0]]

    return render_template(
        'admin.audit_logs.html',
        stats=stats,
        logs=items,
        pagination=pagination,
        q=q,
        categories=categories,
        actions=actions,
        statuses=statuses,
        target_types=target_types,
        selected={
            'category': category,
            'action': action,
            'status': status,
            'target_type': target_type,
            'actor_email': actor_email,
            'start_date': start_date,
            'end_date': end_date,
            'sort_by': sort_by,
            'sort_dir': sort_dir,
            'per_page': per_page,
        }
    )


@admin_bp.route('/support_tickets')
@login_required
def support_tickets():
    # Server-side search, pagination, and CSV export
    q = (request.args.get('q') or '').strip()
    page = int(request.args.get('page') or 1)
    per_page = int(request.args.get('per_page') or 20)

    base = SupportTicket.query.outerjoin(User, SupportTicket.user_id == User.id)

    if q:
        like_q = f"%{q}%"
        base = base.filter(
            or_(
                SupportTicket.subject.ilike(like_q),
                SupportTicket.description.ilike(like_q),
                User.name.ilike(like_q),
                User.email.ilike(like_q)
            )
        )

    # Advanced filters: status, date range
    status = (request.args.get('status') or '').strip()
    start_date = (request.args.get('start_date') or '').strip()
    end_date = (request.args.get('end_date') or '').strip()

    if status:
        base = base.filter(SupportTicket.status == status)

    try:
        if start_date:
            sd = datetime.fromisoformat(start_date)
            base = base.filter(SupportTicket.created_at >= sd)
        if end_date:
            ed = datetime.fromisoformat(end_date)
            base = base.filter(SupportTicket.created_at <= ed)
    except Exception:
        # ignore parse errors and continue
        pass

    # Sorting
    sort_by = (request.args.get('sort_by') or 'created_at').strip()
    sort_dir = (request.args.get('sort_dir') or 'desc').strip().lower()
    order_col = SupportTicket.created_at
    if sort_by == 'user_name':
        order_col = User.name
    elif sort_by == 'status':
        order_col = SupportTicket.status
    elif sort_by == 'created_at':
        order_col = SupportTicket.created_at

    if sort_dir == 'asc':
        base = base.order_by(order_col.asc())
    else:
        base = base.order_by(order_col.desc())

    # CSV export if requested
    if request.args.get('export') == 'csv':
        tickets_all = base.all()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['id', 'user_id', 'user_name', 'user_email', 'subject', 'description', 'status', 'created_at'])
        for t in tickets_all:
            writer.writerow([
                t.id,
                t.user_id,
                getattr(t.user, 'name', '') if getattr(t, 'user', None) else '',
                getattr(t.user, 'email', '') if getattr(t, 'user', None) else '',
                t.subject,
                t.description,
                t.status,
                getattr(t, 'created_at', '')
            ])
        resp = make_response(output.getvalue())
        resp.headers['Content-Type'] = 'text/csv'
        resp.headers['Content-Disposition'] = 'attachment; filename="support_tickets.csv"'
        return resp

    pagination = base.paginate(page=page, per_page=per_page, error_out=False)
    tickets = pagination.items
    stats = get_stats()
    return render_template('admin.support_tickets.html', tickets=tickets, stats=stats, pagination=pagination, q=q)


@admin_bp.route('/support_tickets/<int:ticket_id>')
@login_required
def support_ticket_view(ticket_id):
    ticket = SupportTicket.query.get_or_404(ticket_id)
    messages = SupportMessage.query.filter_by(user_id=ticket.user_id).order_by(SupportMessage.created_at.desc()).all()
    return render_template('admin.support_ticket_view.html', ticket=ticket, messages=messages)


@admin_bp.route('/support_tickets/<int:ticket_id>/resolve', methods=['POST'])
@login_required
def support_ticket_resolve(ticket_id):
    ticket = SupportTicket.query.get_or_404(ticket_id)
    ticket.status = 'resolved'
    db.session.commit()
    log_admin_action(
        'support_ticket_resolve',
        target_type='support_ticket',
        target_id=ticket_id,
        details={'new_status': 'resolved'}
    )
    flash('Support ticket marked resolved.', 'success')
    return redirect(url_for('admin.support_tickets'))


# --- Operations Dashboard (High-impact single view)
@admin_bp.route('/operations')
@login_required
def operations():
    stats = get_stats()

    # quick lists for the dashboard
    try:
        open_maintenance = MaintenanceRequest.query.filter(MaintenanceRequest.status != 'resolved').order_by(MaintenanceRequest.sla_due.asc().nulls_last(), MaintenanceRequest.created_at.desc()).limit(20).all()
    except Exception:
        open_maintenance = []

    try:
        unresolved_support = SupportTicket.query.filter(SupportTicket.status != 'resolved').order_by(SupportTicket.created_at.desc()).limit(20).all()
    except Exception:
        unresolved_support = []

    try:
        recent_payment_issues = Payment.query.filter((Payment.status.ilike('%fail%')) | (Payment.status.ilike('%error%'))).order_by(Payment.created_at.desc()).limit(20).all()
    except Exception:
        recent_payment_issues = []

    return render_template('admin.operations.html', stats=stats, open_maintenance=open_maintenance, unresolved_support=unresolved_support, recent_payment_issues=recent_payment_issues)


@admin_bp.route('/maintenance_queue')
@login_required
def maintenance_queue():
    # Filters
    status = (request.args.get('status') or '').strip()
    page = int(request.args.get('page') or 1)
    per_page = int(request.args.get('per_page') or 25)
    sort_by = (request.args.get('sort_by') or '').strip()
    sort_dir = (request.args.get('sort_dir') or 'asc').strip().lower()

    base = MaintenanceRequest.query
    if status:
        base = base.filter(MaintenanceRequest.status == status)

    # Order by requested sort, default SLA then creation
    if sort_by == 'id':
        order_col = MaintenanceRequest.id
    elif sort_by == 'status':
        order_col = MaintenanceRequest.status
    elif sort_by == 'sla':
        order_col = MaintenanceRequest.sla_due
    else:
        order_col = None

    if order_col is not None:
        if sort_dir == 'asc':
            base = base.order_by(order_col.asc())
        else:
            base = base.order_by(order_col.desc())
    else:
        base = base.order_by(MaintenanceRequest.sla_due.asc().nulls_last(), MaintenanceRequest.created_at.desc())

    pagination = base.paginate(page=page, per_page=per_page, error_out=False)
    items = pagination.items
    stats = get_stats()
    from datetime import datetime, timedelta
    now = datetime.utcnow()
    td = timedelta
    # Provide a simple list of landlords (users with role landlord)
    landlords = User.query.filter(User.role.ilike('%landlord%')).all()
    canned_responses = [
        'Acknowledged. We will assign a technician within 24 hours.',
        'Please provide more details and photos if possible.',
        'Escalating to landlord for immediate attention.',
    ]
    return render_template('admin.maintenance_queue.html', items=items, pagination=pagination, stats=stats, landlords=landlords, canned_responses=canned_responses, now=now, timedelta=td, current_sort=sort_by, current_dir=sort_dir, status_filter=status)


@admin_bp.route('/maintenance/bulk_assign', methods=['POST'])
@login_required
def maintenance_bulk_assign():
    ids = request.form.getlist('ids')
    landlord_id = request.form.get('landlord_id')
    assigned = 0
    if not ids or not landlord_id:
        flash('No items or landlord selected.', 'danger')
        return redirect(url_for('admin.maintenance_queue'))

    for mid in ids:
        req = MaintenanceRequest.query.get(mid)
        if not req:
            continue
        try:
            req.assigned_to = int(landlord_id)
            req.status = 'assigned'
            assigned += 1
        except Exception:
            continue

    db.session.commit()
    log_admin_action(
        'maintenance_bulk_assign',
        target_type='maintenance_request',
        target_id='bulk',
        details={'assigned_count': assigned, 'landlord_id': landlord_id, 'ids': ids}
    )
    flash(f'Assigned {assigned} maintenance request(s).', 'success')
    return redirect(url_for('admin.maintenance_queue'))


@admin_bp.route('/maintenance/respond', methods=['POST'])
@login_required
def maintenance_respond():
    req_id = request.form.get('request_id')
    response_text = request.form.get('response')
    canned = request.form.get('canned')
    if canned and not response_text:
        response_text = canned

    if not req_id or not response_text:
        flash('Missing request or response text.', 'danger')
        return redirect(url_for('admin.maintenance_queue'))

    req = MaintenanceRequest.query.get(req_id)
    if not req:
        flash('Request not found.', 'danger')
        return redirect(url_for('admin.maintenance_queue'))

    comment = MaintenanceComment(request_id=req.id, author_id=current_user.id, role='admin', comment=response_text)
    db.session.add(comment)
    # optionally change status
    if request.form.get('set_resolved') == '1':
        req.status = 'resolved'

    db.session.commit()
    log_admin_action(
        'maintenance_respond',
        target_type='maintenance_request',
        target_id=req.id,
        details={'set_resolved': request.form.get('set_resolved') == '1'}
    )
    flash('Response added to request timeline.', 'success')
    return redirect(url_for('admin.maintenance_queue'))

# --- Platform Settings ---
@admin_bp.route('/platform_settings',  methods=['GET', 'POST'])
@login_required
def platform_settings():
    # ensure settings table exists
    if not inspect(db.engine).has_table('system_setting'):
        db.create_all()

    if request.method == 'POST':
        # Read values from form
        max_listings = request.form.get('max_listings', '').strip()
        default_status = request.form.get('default_status', 'active')
        notification_enabled = 'notification_enabled' in request.form
        maintenance_mode = 'maintenance_mode' in request.form
        maintenance_start = request.form.get('maintenance_start') or ''
        maintenance_end = request.form.get('maintenance_end') or ''
        feature_signup_enabled = 'feature_signup_enabled' in request.form
        feature_live_chat_enabled = 'feature_live_chat_enabled' in request.form
        feature_support_escalation_enabled = 'feature_support_escalation_enabled' in request.form
        feature_dark_mode_enabled = 'feature_dark_mode_enabled' in request.form
        signup_allowed_roles = request.form.get('signup_allowed_roles', 'tenant,landlord,service')
        report_schedule_enabled = 'report_schedule_enabled' in request.form
        report_schedule_interval_minutes = request.form.get('report_schedule_interval_minutes', '1440').strip()
        report_schedule_datasets = request.form.get('report_schedule_datasets', 'summary,finance,occupancy,maintenance').strip()
        report_schedule_format = request.form.get('report_schedule_format', 'csv').strip().lower()
        parsed_roles = _parse_signup_roles(signup_allowed_roles)

        if not parsed_roles:
            parsed_roles = ['tenant', 'landlord', 'service']

        try:
            interval_minutes = int(report_schedule_interval_minutes)
        except Exception:
            interval_minutes = 1440
        interval_minutes = max(15, interval_minutes)
        if report_schedule_format not in ('csv', 'xlsx', 'both'):
            report_schedule_format = 'csv'

        # Persist
        SystemSetting.set('max_listings', str(max_listings))
        SystemSetting.set('default_status', default_status)
        SystemSetting.set('notification_enabled', '1' if notification_enabled else '0')
        SystemSetting.set('maintenance_mode', '1' if maintenance_mode else '0')
        SystemSetting.set('maintenance_start', maintenance_start)
        SystemSetting.set('maintenance_end', maintenance_end)
        SystemSetting.set('feature_signup_enabled', '1' if feature_signup_enabled else '0')
        SystemSetting.set('feature_live_chat_enabled', '1' if feature_live_chat_enabled else '0')
        SystemSetting.set('feature_support_escalation_enabled', '1' if feature_support_escalation_enabled else '0')
        SystemSetting.set('feature_dark_mode_enabled', '1' if feature_dark_mode_enabled else '0')
        SystemSetting.set('signup_allowed_roles', ','.join(parsed_roles))
        SystemSetting.set('report_schedule_enabled', '1' if report_schedule_enabled else '0')
        SystemSetting.set('report_schedule_interval_minutes', str(interval_minutes))
        SystemSetting.set('report_schedule_datasets', report_schedule_datasets)
        SystemSetting.set('report_schedule_format', report_schedule_format)

        log_admin_action(
            'platform_settings_update',
            target_type='platform_settings',
            target_id='global',
            details={
                'max_listings': max_listings,
                'default_status': default_status,
                'notification_enabled': notification_enabled,
                'maintenance_mode': maintenance_mode,
                'maintenance_start': maintenance_start,
                'maintenance_end': maintenance_end,
                'feature_signup_enabled': feature_signup_enabled,
                'feature_live_chat_enabled': feature_live_chat_enabled,
                'feature_support_escalation_enabled': feature_support_escalation_enabled,
                'feature_dark_mode_enabled': feature_dark_mode_enabled,
                'signup_allowed_roles': parsed_roles,
                'report_schedule_enabled': report_schedule_enabled,
                'report_schedule_interval_minutes': interval_minutes,
                'report_schedule_datasets': report_schedule_datasets,
                'report_schedule_format': report_schedule_format,
            }
        )

        flash('Platform settings saved.', 'success')
        return redirect(url_for('admin.platform_settings'))

    # GET: build settings dict from DB
    settings = {
        'max_listings': SystemSetting.get('max_listings', '10'),
        'default_status': SystemSetting.get('default_status', 'active'),
        'notification_enabled': SystemSetting.get('notification_enabled', '1') == '1',
        'maintenance_mode': SystemSetting.get('maintenance_mode', '0') == '1',
        'maintenance_start': SystemSetting.get('maintenance_start', ''),
        'maintenance_end': SystemSetting.get('maintenance_end', ''),
        'feature_signup_enabled': SystemSetting.get('feature_signup_enabled', '1') == '1',
        'feature_live_chat_enabled': SystemSetting.get('feature_live_chat_enabled', '1') == '1',
        'feature_support_escalation_enabled': SystemSetting.get('feature_support_escalation_enabled', '1') == '1',
        'feature_dark_mode_enabled': SystemSetting.get('feature_dark_mode_enabled', '1') == '1',
        'signup_allowed_roles': SystemSetting.get('signup_allowed_roles', 'tenant,landlord,service'),
        'report_schedule_enabled': SystemSetting.get('report_schedule_enabled', '0') == '1',
        'report_schedule_interval_minutes': SystemSetting.get('report_schedule_interval_minutes', '1440'),
        'report_schedule_datasets': SystemSetting.get('report_schedule_datasets', 'summary,finance,occupancy,maintenance'),
        'report_schedule_format': SystemSetting.get('report_schedule_format', 'csv'),
        'report_schedule_last_run_at': SystemSetting.get('report_schedule_last_run_at', ''),
        'report_schedule_last_result': SystemSetting.get('report_schedule_last_result', ''),
    }
    return render_template('platform_settings.html', settings=settings)


@admin_bp.route('/email_templates', methods=['GET', 'POST'])
@login_required
def email_templates():
    _ensure_default_email_templates()

    templates = EmailTemplate.query.order_by(EmailTemplate.category.asc(), EmailTemplate.name.asc()).all()
    selected_id = request.args.get('template_id', type=int)
    selected_template = None

    if templates:
        selected_template = next((item for item in templates if item.id == selected_id), templates[0])

    if request.method == 'POST':
        template_id = request.form.get('template_id', type=int)
        template = EmailTemplate.query.get(template_id) if template_id else None
        is_new_template = template is None

        if template is None:
            template = EmailTemplate(
                key=(request.form.get('key') or '').strip(),
                name=(request.form.get('name') or '').strip(),
                category=(request.form.get('category') or 'general').strip() or 'general',
            )
            db.session.add(template)

        template.key = (request.form.get('key') or template.key or '').strip()
        template.name = (request.form.get('name') or template.name or '').strip()
        template.category = (request.form.get('category') or template.category or 'general').strip() or 'general'
        template.description = (request.form.get('description') or '').strip() or None
        template.subject = (request.form.get('subject') or '').strip()
        template.html_body = (request.form.get('html_body') or '').strip()
        template.text_body = (request.form.get('text_body') or '').strip() or None
        template.is_active = 'is_active' in request.form
        template.is_default = 'is_default' in request.form
        template.set_variables((request.form.get('variables') or '').split(','))
        template.updated_by_id = getattr(current_user, 'id', None)

        if not template.key or not template.name or not template.subject or not template.html_body:
            db.session.rollback()
            flash('Key, name, subject, and HTML body are required.', 'danger')
            selected_template = template
            preview_context = _template_preview_context(selected_template) if selected_template else {}
            return render_template(
                'admin.email_templates.html',
                templates=templates,
                selected_template=selected_template,
                preview_context=preview_context,
                preview_rendered=_render_email_preview(selected_template, preview_context),
            )

        if is_new_template:
            template.created_by_id = getattr(current_user, 'id', None)

        _snapshot_email_template(
            template,
            created_by_id=getattr(current_user, 'id', None),
            change_notes=request.form.get('change_notes') or 'Admin template update',
        )
        db.session.commit()

        log_admin_action(
            'email_template_save',
            target_type='email_template',
            target_id=template.id,
            details={
                'key': template.key,
                'name': template.name,
                'category': template.category,
                'is_active': template.is_active,
                'is_default': template.is_default,
            }
        )
        flash('Email template saved.', 'success')
        return redirect(url_for('admin.email_templates', template_id=template.id))

    preview_context = _template_preview_context(selected_template) if selected_template else {}
    preview_rendered = _render_email_preview(selected_template, preview_context)
    return render_template(
        'admin.email_templates.html',
        templates=templates,
        selected_template=selected_template,
        preview_context=preview_context,
        preview_rendered=preview_rendered,
    )


@admin_bp.route('/email_templates/<int:template_id>/test_send', methods=['POST'])
@login_required
def email_template_test_send(template_id):
    _ensure_default_email_templates()

    template = EmailTemplate.query.get_or_404(template_id)
    recipient_email = (request.form.get('recipient_email') or '').strip()
    recipient_name = (request.form.get('recipient_name') or current_user.name or 'Admin User').strip()

    if not recipient_email:
        flash('A test recipient email is required.', 'danger')
        return redirect(url_for('admin.email_templates', template_id=template.id))

    preview_context = _template_preview_context(template)
    preview_context['name'] = recipient_name or preview_context.get('name') or 'Admin User'
    preview_context['email'] = recipient_email

    fallback_context = preview_context.copy()
    result = send_templated_email(
        template.key,
        recipient_email,
        fallback_context,
        template.subject,
        template.html_body,
        template.text_body or '',
        mode='test',
        created_by_id=getattr(current_user, 'id', None),
    )

    log_admin_action(
        'email_template_test_send',
        target_type='email_template',
        target_id=template.id,
        status='success' if result else 'failed',
        details={
            'key': template.key,
            'recipient_email': recipient_email,
        }
    )

    if result:
        flash(f'Test email sent to {recipient_email}.', 'success')
    else:
        flash('Test email could not be sent. Check template content and SendGrid settings.', 'danger')

    return redirect(url_for('admin.email_templates', template_id=template.id))


@admin_bp.route('/email_templates/<int:template_id>/versions/<int:version_id>/restore', methods=['POST'])
@login_required
def email_template_version_restore(template_id, version_id):
    _ensure_default_email_templates()

    template = EmailTemplate.query.get_or_404(template_id)
    version = EmailTemplateVersion.query.filter_by(id=version_id, template_id=template.id).first_or_404()

    _restore_email_template_version(template, version, actor_user_id=getattr(current_user, 'id', None))
    template.updated_by_id = getattr(current_user, 'id', None)
    db.session.commit()

    log_admin_action(
        'email_template_version_restore',
        target_type='email_template_version',
        target_id=version.id,
        details={
            'template_key': template.key,
            'version_number': version.version_number,
        }
    )
    flash(f'Template restored from version {version.version_number}.', 'success')
    return redirect(url_for('admin.email_templates', template_id=template.id))


@admin_bp.route('/email_templates/<int:template_id>/versions/<int:version_id>/delete', methods=['POST'])
@login_required
def email_template_version_delete(template_id, version_id):
    _ensure_default_email_templates()

    template = EmailTemplate.query.get_or_404(template_id)
    version = EmailTemplateVersion.query.filter_by(id=version_id, template_id=template.id).first_or_404()
    version_number = version.version_number

    db.session.delete(version)
    db.session.commit()

    log_admin_action(
        'email_template_version_delete',
        target_type='email_template_version',
        target_id=version_id,
        details={
            'template_key': template.key,
            'version_number': version_number,
        }
    )
    flash(f'Version {version_number} deleted.', 'success')
    return redirect(url_for('admin.email_templates', template_id=template.id))


@admin_bp.route('/report_schedule/run_now', methods=['POST'])
@login_required
def run_report_schedule_now():
    try:
        from services.report_scheduler import run_scheduled_report_job

        result = run_scheduled_report_job(force=True)
        log_admin_action(
            'report_schedule_run_now',
            target_type='report',
            target_id='scheduled_job',
            details={
                'ran': result.get('ran'),
                'reason': result.get('reason'),
                'datasets': result.get('datasets', []),
                'counts': result.get('counts', {}),
            }
        )
        if result.get('ran'):
            flash('Scheduled report job executed successfully.', 'success')
        else:
            flash(f"Scheduled report job did not run: {result.get('reason', 'unknown')}", 'warning')
    except Exception:
        logger.exception('Failed to run scheduled report job manually')
        flash('Failed to run scheduled report job.', 'danger')

    return redirect(url_for('admin.platform_settings'))

# --- Language Settings ---
@admin_bp.route('/set_language', methods=['POST'])
@login_required
def set_language():
    new_language = request.form.get("language", "English")
    current_user.language = new_language
    db.session.commit()
    flash("Language updated!", "success")
    return redirect(url_for('admin.dashboard'))

# --- Announcements ---
@admin_bp.route('/send_announcement', methods=['POST'])
@login_required
def send_announcement():
    # Accept either 'message' or legacy 'announcement' form key.
    message = request.form.get("message") or request.form.get("announcement")

    if not message:
        flash("Announcement message cannot be empty.", "danger")
        return redirect(url_for('admin.dashboard'))

    # Placeholder logic — later you can extend this to send emails/SMS/notifications
    flash("Announcement queued (placeholder).", "success")
    return redirect(url_for('admin.dashboard'))


@admin_bp.route('/system_updates', methods=['GET', 'POST'])
@login_required
def system_updates():
    # Keep feature functional even when Alembic history is out of sync.
    if not inspect(db.engine).has_table('system_update_subscriber'):
        db.create_all()

    subscribers = SystemUpdateSubscriber.query.filter_by(is_active=True).order_by(SystemUpdateSubscriber.created_at.desc()).all()
    topic_choices = {
        'all': 'All Subscribers',
        'platform_updates': 'Platform updates',
        'security_alerts': 'Security alerts',
        'maintenance_notices': 'Maintenance notices',
        'new_features': 'New features',
    }

    def topic_match(subscriber, topic_key):
        if topic_key == 'all':
            return True
        saved_topics = [t.strip() for t in (subscriber.topics or '').split(',') if t.strip()]
        return topic_key in saved_topics

    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        body = (request.form.get('body') or '').strip()
        selected_topic = (request.form.get('topic') or 'all').strip()

        if selected_topic not in topic_choices:
            selected_topic = 'all'

        if not title or not body:
            flash('Title and update message are required.', 'danger')
            return render_template(
                'system_updates.html',
                subscribers=subscribers,
                topic_choices=topic_choices,
                selected_topic=selected_topic,
            )

        recipients = [sub for sub in subscribers if topic_match(sub, selected_topic)]

        if not recipients:
            flash('No matching subscribers found for the selected topic.', 'warning')
            return render_template(
                'system_updates.html',
                subscribers=subscribers,
                topic_choices=topic_choices,
                selected_topic=selected_topic,
            )

# --- Role management routes ---
@admin_bp.route('/roles')
@login_required
def roles():
    from sqlalchemy import inspect
    from models.models import Role, Permission
    # ensure tables exist
    if not inspect(db.engine).has_table('role'):
        db.create_all()
    roles = Role.query.order_by(Role.name).all()
    permissions = Permission.query.order_by(Permission.name).all()
    return render_template('admin.roles.html', roles=roles, permissions=permissions)


@admin_bp.route('/roles/create', methods=['GET', 'POST'])
@login_required
def create_role():
    from models.models import Role, Permission
    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()
        description = (request.form.get('description') or '').strip()
        perm_ids = request.form.getlist('permissions')
        if not name:
            flash('Role name is required.', 'danger')
            return redirect(url_for('admin.roles'))
        if Role.query.filter_by(name=name).first():
            flash('Role with that name already exists.', 'danger')
            return redirect(url_for('admin.roles'))
        role = Role(name=name, description=description)
        for pid in perm_ids:
            p = Permission.query.get(pid)
            if p:
                role.permissions.append(p)
        db.session.add(role)
        db.session.commit()
        log_admin_action(
            'role_create',
            target_type='role',
            target_id=role.id,
            details={'name': role.name, 'permission_ids': perm_ids}
        )
        flash('Role created.', 'success')
        return redirect(url_for('admin.roles'))
    # GET -> show form
    permissions = Permission.query.order_by(Permission.name).all()
    return render_template('admin.role_form.html', permissions=permissions, role=None)


@admin_bp.route('/roles/<int:role_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_role(role_id):
    from models.models import Role, Permission
    role = Role.query.get_or_404(role_id)
    if request.method == 'POST':
        role.name = (request.form.get('name') or '').strip()
        role.description = (request.form.get('description') or '').strip()
        perm_ids = request.form.getlist('permissions')
        role.permissions = []
        for pid in perm_ids:
            p = Permission.query.get(pid)
            if p:
                role.permissions.append(p)
        db.session.commit()
        log_admin_action(
            'role_edit',
            target_type='role',
            target_id=role.id,
            details={'name': role.name, 'permission_ids': perm_ids}
        )
        flash('Role updated.', 'success')
        return redirect(url_for('admin.roles'))
    permissions = Permission.query.order_by(Permission.name).all()
    return render_template('admin.role_form.html', role=role, permissions=permissions)


@admin_bp.route('/roles/<int:role_id>/delete', methods=['POST'])
@login_required
def delete_role(role_id):
    from models.models import Role
    role = Role.query.get_or_404(role_id)
    role_name = role.name
    # prevent deleting core roles maybe
    db.session.delete(role)
    db.session.commit()
    log_admin_action(
        'role_delete',
        target_type='role',
        target_id=role_id,
        details={'name': role_name}
    )
    flash('Role deleted.', 'success')
    return redirect(url_for('admin.roles'))


# --- Permission management routes ---
@admin_bp.route('/permissions')
@login_required
def permissions():
    from sqlalchemy import inspect
    from models.models import Permission
    # seed default permissions if none exist
    if not inspect(db.engine).has_table('permission'):
        db.create_all()
    if Permission.query.count() == 0:
        defaults = [
            ('manage_users', 'Create/Edit/Delete users'),
            ('manage_properties', 'Create/Edit/Delete properties'),
            ('view_reports', 'View reports and exports'),
            ('manage_roles', 'Create/Edit/Delete roles and permissions'),
            ('download_audit_log', 'Download audit logs'),
            ('send_announcements', 'Send platform announcements')
        ]
        for name, desc in defaults:
            db.session.add(Permission(name=name, description=desc))
        db.session.commit()

    permissions = Permission.query.order_by(Permission.name).all()
    return render_template('admin.permissions.html', permissions=permissions)


@admin_bp.route('/permissions/create', methods=['GET', 'POST'])
@login_required
def create_permission():
    from models.models import Permission
    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()
        description = (request.form.get('description') or '').strip()
        if not name:
            flash('Permission name is required.', 'danger')
            return redirect(url_for('admin.permissions'))
        if Permission.query.filter_by(name=name).first():
            flash('Permission already exists.', 'danger')
            return redirect(url_for('admin.permissions'))
        p = Permission(name=name, description=description)
        db.session.add(p)
        db.session.commit()
        log_admin_action(
            'permission_create',
            target_type='permission',
            target_id=p.id,
            details={'name': p.name}
        )
        flash('Permission created.', 'success')
        return redirect(url_for('admin.permissions'))
    return render_template('admin.permission_form.html', permission=None)


@admin_bp.route('/permissions/<int:perm_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_permission(perm_id):
    from models.models import Permission
    p = Permission.query.get_or_404(perm_id)
    if request.method == 'POST':
        p.name = (request.form.get('name') or '').strip()
        p.description = (request.form.get('description') or '').strip()
        db.session.commit()
        log_admin_action(
            'permission_edit',
            target_type='permission',
            target_id=p.id,
            details={'name': p.name}
        )
        flash('Permission updated.', 'success')
        return redirect(url_for('admin.permissions'))
    return render_template('admin.permission_form.html', permission=p)


@admin_bp.route('/permissions/<int:perm_id>/delete', methods=['POST'])
@login_required
def delete_permission(perm_id):
    from models.models import Permission
    p = Permission.query.get_or_404(perm_id)
    perm_name = p.name
    db.session.delete(p)
    db.session.commit()
    log_admin_action(
        'permission_delete',
        target_type='permission',
        target_id=perm_id,
        details={'name': perm_name}
    )
    flash('Permission deleted.', 'success')
    return redirect(url_for('admin.permissions'))

    sent = 0
    failed = 0
    for sub in recipients:
        if send_system_update_email(sub.email, title, body):
            sent += 1
        else:
            failed += 1

    if sent > 0:
        flash(f'Update sent to {sent} subscriber(s).', 'success')
    if failed > 0:
        flash(f'Failed to deliver to {failed} subscriber(s).', 'warning')

    return render_template(
        'system_updates.html',
        subscribers=subscribers,
        topic_choices=topic_choices,
        selected_topic=selected_topic,
    )

    return render_template(
        'system_updates.html',
        subscribers=subscribers,
        topic_choices=topic_choices,
        selected_topic='all',
    )

# --- Bulk User/Property Actions ---
@admin_bp.route('/bulk_action', methods=['POST'])
@login_required
def bulk_action():
    action = request.form.get("action")
    ids = request.form.getlist("ids")  # Expecting checkboxes named "ids" in your template

    if not action or not ids:
        flash("No action or items selected.", "danger")
        return redirect(url_for('admin.dashboard'))

    if action == "delete_users":
        # require explicit confirmation for hard delete
        confirm_mode = request.form.get('confirm')
        dry_run = request.form.get('dry_run') == '1'
        preview = []
        for user_id in ids:
            user = User.query.get(user_id)
            if not user:
                continue
            if confirm_mode == 'hard':
                preview.append({'id': user.id, 'username': getattr(user, 'name', str(user.id)), 'action': 'permanently delete'})
            else:
                preview.append({'id': user.id, 'username': getattr(user, 'name', str(user.id)), 'action': 'soft-deactivate'})

        if dry_run:
            return render_template('admin.bulk_preview.html', items=preview, action=action, confirm_mode=confirm_mode)
        deleted = 0
        for user_id in ids:
            user = User.query.get(user_id)
            if not user:
                continue
            if confirm_mode == 'hard':
                success, error = delete_user_and_dependents(user)
                if success:
                    deleted += 1
                    logger.info(f"Admin {current_user.id} hard-deleted user {user.id}")
            else:
                setattr(user, 'is_active', False)
                deleted += 1
        db.session.commit()
        log_admin_action(
            'bulk_delete_users',
            target_type='user',
            target_id='bulk',
            details={'count': deleted, 'mode': confirm_mode, 'ids': ids}
        )
        flash(f"{deleted} user(s) processed (soft-deactivate or hard-delete).", "success")

    elif action == "notify":
        subject = (request.form.get('subject') or '').strip()
        body = (request.form.get('message') or request.form.get('body') or '').strip()
        dry_run = request.form.get('dry_run') == '1'
        preview = []
        recipients = []

        for user_id in ids:
            user = User.query.get(user_id)
            if not user or not getattr(user, 'email', None):
                continue
            recipients.append(user)
            preview.append({
                'id': user.id,
                'username': getattr(user, 'name', str(user.id)),
                'action': f"email to {user.email}",
            })

        if not subject or not body:
            flash('Subject and message are required for bulk email.', 'danger')
            return redirect(url_for('admin.dashboard'))

        if dry_run:
            return render_template(
                'admin.bulk_preview.html',
                items=preview,
                action=action,
                confirm_mode='soft',
                bulk_subject=subject,
                bulk_message=body,
                bulk_recipient_count=len(recipients),
            )

        sent_count = 0
        for user in recipients:
            enqueue_system_update_email(user.email, subject, body)
            sent_count += 1

        log_admin_action(
            'bulk_email_users',
            target_type='user',
            target_id='bulk',
            details={
                'count': sent_count,
                'subject': subject,
                'ids': ids,
            }
        )
        flash(f'Bulk email queued for {sent_count} user(s).', 'success')

    elif action == "delete_properties":
        confirm_mode = request.form.get('confirm')
        dry_run = request.form.get('dry_run') == '1'
        preview = []
        for house_id in ids:
            house = House.query.get(house_id)
            if not house:
                continue
            if confirm_mode == 'hard':
                preview.append({'id': house.id, 'title': getattr(house, 'title', str(house.id)), 'action': 'permanently delete'})
            else:
                preview.append({'id': house.id, 'title': getattr(house, 'title', str(house.id)), 'action': 'mark unavailable'})

        if dry_run:
            return render_template('admin.bulk_preview.html', items=preview, action=action, confirm_mode=confirm_mode)
        processed = 0
        for house_id in ids:
            house = House.query.get(house_id)
            if not house:
                continue
            if confirm_mode == 'hard':
                db.session.delete(house)
                logger.info(f"Admin {current_user.id} hard-deleted property {house.id}")
            else:
                house.available = False
                logger.info(f"Admin {current_user.id} marked property {house.id} unavailable (soft)")
            processed += 1
        db.session.commit()
        log_admin_action(
            'bulk_delete_properties',
            target_type='property',
            target_id='bulk',
            details={'count': processed, 'mode': confirm_mode, 'ids': ids}
        )
        flash(f"{processed} property(ies) processed.", "success")

    else:
        flash("Invalid bulk action.", "danger")

    return redirect(url_for('admin.dashboard'))

# --- Single User Actions ---
@admin_bp.route('/user_action/<int:user_id>', methods=['POST'])
@login_required
def user_action(user_id):
    action = request.form.get("action")
    user = User.query.get_or_404(user_id)

    if action == "delete":
        # Prevent self-delete
        if current_user.id == user.id:
            flash("You cannot delete your own account.", "danger")
            return redirect(url_for('admin.manage_users'))

        success, error = delete_user_and_dependents(user)
        if success:
            logger.info(f"Admin {current_user.id} hard-deleted user {user.id}")
            log_admin_action(
                'user_action_delete',
                target_type='user',
                target_id=user.id,
                details={'action': 'delete'}
            )
            flash(f"User {getattr(user, 'name', user.id)} deleted.", "success")
        else:
            log_admin_action(
                'user_action_delete',
                target_type='user',
                target_id=user.id,
                status='failed',
                details={'action': 'delete', 'error': error}
            )
            flash(f"Could not delete user: {error}", "danger")

    elif action == "deactivate":
        user.is_active = False
        db.session.commit()
        log_admin_action(
            'user_action_deactivate',
            target_type='user',
            target_id=user.id,
            details={'action': 'deactivate'}
        )
        flash(f"User {getattr(user, 'name', user.id)} deactivated.", "warning")

    elif action == "activate":
        user.is_active = True
        db.session.commit()
        log_admin_action(
            'user_action_activate',
            target_type='user',
            target_id=user.id,
            details={'action': 'activate'}
        )
        flash(f"User {getattr(user, 'name', user.id)} activated.", "success")

    elif action == "reset_password":
        if not getattr(user, 'email', None):
            flash("This user does not have an email address for a reset link.", "danger")
            return redirect(url_for('admin.manage_users'))

        if user.role != 'admin':
            flash("Password reset links are currently restricted to admin accounts.", "warning")
            return redirect(url_for('admin.manage_users'))

        from routes.auth_routes import _queue_password_reset

        _queue_password_reset(user)
        log_admin_action(
            'user_reset_password_link',
            category='security',
            target_type='user',
            target_id=user.id,
            details={'email': user.email, 'role': user.role}
        )
        flash(f"Password reset link queued for {user.email}.", "success")

    else:
        flash("Invalid user action.", "danger")

    return redirect(url_for('admin.manage_users'))


# --- Impersonation (read-only) ---
@admin_bp.route('/impersonate/<int:user_id>', methods=['POST'])
@login_required
def impersonate(user_id):
    if not is_approved_admin(current_user):
        flash('Access denied.', 'danger')
        return redirect(url_for('admin.dashboard'))

    target = User.query.get_or_404(user_id)
    if target.id == current_user.id:
        flash('You cannot impersonate yourself.', 'warning')
        return redirect(url_for('admin.manage_users'))

    # Save admin id so we can return to it later
    session['admin_id'] = current_user.id
    session['is_impersonating'] = True
    # Remove admin entry token to avoid accidental admin area access during impersonation
    session.pop('admin_entry_granted', None)

    login_user(target)
    log_admin_action(
        'impersonation_start',
        category='security',
        target_type='user',
        target_id=target.id,
        details={'target_email': target.email}
    )
    flash(f"Now impersonating {getattr(target, 'name', target.id)} (read-only).", 'info')
    return redirect(url_for('main.index'))


@admin_bp.route('/stop_impersonate', methods=['POST'])
@login_required
def stop_impersonate():
    admin_id = session.pop('admin_id', None)
    session.pop('is_impersonating', None)
    # Restore admin session if possible
    if admin_id:
        admin = User.query.get(admin_id)
        if admin:
            login_user(admin)
            session['admin_entry_granted'] = True
            log_admin_action(
                'impersonation_stop',
                category='security',
                target_type='user',
                target_id=admin.id,
                details={'restored_admin_email': admin.email},
                actor_user_id=admin.id,
                actor_email=admin.email,
            )
            flash('Stopped impersonation. You are back as admin.', 'success')
            return redirect(url_for('admin.dashboard'))

    # Fallback: log out
    logout_user()
    flash('Stopped impersonation. Please sign in.', 'info')
    return redirect(url_for('auth.login'))


@admin_bp.route('/revoke_sessions', methods=['POST'])
@login_required
def revoke_admin_sessions():
    """Revoke all active admin sessions by rotating the shared session nonce."""
    new_nonce = secrets.token_hex(16)
    SystemSetting.set('admin_session_nonce', new_nonce)

    log_admin_action(
        'admin_sessions_revoke_all',
        category='security',
        target_type='session',
        target_id='admin_global',
        details={'rotated_nonce': True}
    )

    clear_admin_totp_verification()
    session.pop('admin_entry_granted', None)
    session.pop('admin_entry_granted_at', None)
    session.pop('admin_last_seen_at', None)
    session.pop('admin_session_nonce', None)
    session.pop('admin_id', None)
    session.pop('is_impersonating', None)
    logout_user()
    flash('All admin sessions were revoked. Please sign in again.', 'success')
    return redirect(url_for('auth.login'))

# --- Export Reports ---
@admin_bp.route('/export_reports')
@login_required
def export_reports():
    dataset = (request.args.get('dataset') or 'summary').strip().lower()
    fmt = (request.args.get('format') or 'csv').strip().lower()
    if fmt not in ('csv', 'xlsx'):
        fmt = 'csv'

    stats = get_stats()

    def build_dataset_rows(dataset_name):
        if dataset_name == 'summary':
            headers = ['metric', 'value']
            rows = [
                ['total_users', stats.get('total_users', 0)],
                ['total_properties', stats.get('total_properties', 0)],
                ['total_transactions', stats.get('total_transactions', 0)],
                ['occupied_properties', stats.get('occupied_properties', 0)],
                ['vacant_properties', stats.get('vacant_properties', 0)],
                ['occupancy_rate', stats.get('occupancy_rate', 0)],
                ['paid_amount_total', stats.get('paid_amount_total', 0)],
                ['revenue_mtd', stats.get('revenue_mtd', 0)],
                ['transactions_mtd', stats.get('transactions_mtd', 0)],
                ['payment_success_rate', stats.get('payment_success_rate', 0)],
                ['payments_pending_count', stats.get('payments_pending_count', 0)],
                ['payment_failures', stats.get('payment_failures', 0)],
                ['maintenance_total', stats.get('maintenance_total', 0)],
                ['maintenance_open', stats.get('maintenance_open', 0)],
                ['maintenance_pending', stats.get('maintenance_pending', 0)],
                ['maintenance_in_progress', stats.get('maintenance_in_progress', 0)],
                ['maintenance_resolved', stats.get('maintenance_resolved', 0)],
                ['support_total', stats.get('support_total', 0)],
                ['support_open', stats.get('support_open', 0)],
                ['support_escalated', stats.get('support_escalated', 0)],
                ['support_resolved', stats.get('support_resolved', 0)],
                ['payments_30d', stats.get('payments_30d', 0)],
                ['maintenance_30d', stats.get('maintenance_30d', 0)],
                ['support_30d', stats.get('support_30d', 0)],
            ]
            roles = stats.get('role_counts') or {}
            rows.extend([
                ['role_tenant', roles.get('tenant', 0)],
                ['role_landlord', roles.get('landlord', 0)],
                ['role_service', roles.get('service', 0)],
                ['role_admin', roles.get('admin', 0)],
            ])
            return headers, rows

        if dataset_name == 'finance':
            payments = Payment.query.order_by(Payment.date.desc()).all()
            headers = ['id', 'tenant_id', 'tenant_email', 'house_id', 'amount', 'payment_month', 'date', 'due_date', 'status', 'transaction_id']
            rows = []
            for p in payments:
                tenant_email = p.tenant.email if getattr(p, 'tenant', None) else ''
                rows.append([
                    p.id,
                    p.tenant_id,
                    tenant_email,
                    p.house_id,
                    float(p.amount or 0),
                    p.payment_month or '',
                    p.date.isoformat() if p.date else '',
                    p.due_date.isoformat() if p.due_date else '',
                    p.status or '',
                    p.transaction_id or '',
                ])
            return headers, rows

        if dataset_name == 'occupancy':
            houses = House.query.order_by(House.id.desc()).all()
            headers = ['id', 'title', 'category', 'location', 'available', 'owner_id', 'rent_amount', 'bedrooms', 'bathrooms']
            rows = []
            for h in houses:
                rows.append([
                    h.id,
                    h.title or '',
                    h.category or '',
                    h.location or '',
                    bool(h.available),
                    h.owner_id,
                    float(h.rent_amount or 0),
                    h.bedrooms or 0,
                    h.bathrooms or 0,
                ])
            return headers, rows

        if dataset_name == 'maintenance':
            requests = MaintenanceRequest.query.order_by(MaintenanceRequest.created_at.desc()).all()
            headers = ['id', 'tenant_id', 'tenant_email', 'house_id', 'issue', 'status', 'created_at', 'sla_due']
            rows = []
            for r in requests:
                tenant_email = r.tenant.email if getattr(r, 'tenant', None) else ''
                rows.append([
                    r.id,
                    r.tenant_id,
                    tenant_email,
                    r.house_id,
                    r.issue or '',
                    r.status or '',
                    r.created_at.isoformat() if r.created_at else '',
                    r.sla_due.isoformat() if r.sla_due else '',
                ])
            return headers, rows

        return None, None

    headers, rows = build_dataset_rows(dataset)
    if headers is None:
        flash('Unknown export dataset requested.', 'warning')
        return redirect(url_for('admin.view_reports'))

    row_count = len(rows)

    if fmt == 'xlsx':
        try:
            import importlib

            openpyxl_module = importlib.import_module('openpyxl')
            Workbook = getattr(openpyxl_module, 'Workbook')

            wb = Workbook()
            ws = wb.active
            ws.title = dataset.capitalize()
            ws.append(headers)
            for row in rows:
                ws.append(row)

            xbuf = io.BytesIO()
            wb.save(xbuf)
            payload = xbuf.getvalue()

            log_admin_action(
                'export_reports_xlsx',
                target_type='report',
                target_id=dataset,
                details={'dataset': dataset, 'format': 'xlsx', 'rows': row_count}
            )

            return (
                payload,
                200,
                {
                    'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    'Content-Disposition': f'attachment; filename="report_{dataset}.xlsx"'
                }
            )
        except Exception:
            flash('XLSX export unavailable. Falling back to CSV.', 'warning')
            fmt = 'csv'

    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(headers)
    for row in rows:
        cw.writerow(row)

    log_admin_action(
        'export_reports_csv',
        target_type='report',
        target_id=dataset,
        details={'dataset': dataset, 'format': 'csv', 'rows': row_count}
    )

    return (
        si.getvalue().encode('utf-8'),
        200,
        {
            'Content-Type': 'text/csv; charset=utf-8',
            'Content-Disposition': f'attachment; filename="report_{dataset}.csv"'
        }
    )


@admin_bp.route('/export_financial')
@login_required
def export_financial():
    # Export payments as CSV. Accept optional start/end ISO dates as query params.
    from models.models import Payment
    import csv, io

    start = request.args.get('start')
    end = request.args.get('end')

    q = Payment.query
    if start:
        try:
            from datetime import datetime
            sdt = datetime.fromisoformat(start)
            q = q.filter(Payment.date >= sdt)
        except Exception:
            pass
    if end:
        try:
            from datetime import datetime
            edt = datetime.fromisoformat(end)
            q = q.filter(Payment.date <= edt)
        except Exception:
            pass

    payments = q.order_by(Payment.date.desc()).all()

    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(['id', 'tenant_id', 'tenant_email', 'amount', 'date', 'reference', 'status'])
    for p in payments:
        tenant_email = p.tenant.email if getattr(p, 'tenant', None) else ''
        cw.writerow([p.id, p.tenant_id, tenant_email, float(p.amount or 0), p.date.isoformat() if p.date else '', getattr(p, 'reference', ''), getattr(p, 'status', '')])

    output = si.getvalue().encode('utf-8')
    log_admin_action(
        'export_financial_csv',
        target_type='report',
        target_id='financial',
        details={'start': start, 'end': end, 'rows': len(payments)}
    )
    return (output, 200, {
        'Content-Type': 'text/csv; charset=utf-8',
        'Content-Disposition': 'attachment; filename="financial_reports.csv"'
    })

# --- Download Audit Log ---
@admin_bp.route('/download_audit_log')
@login_required
def download_audit_log():
    # Placeholder: later we can stream a CSV/Excel/JSON file
    flash("Audit log downloaded successfully (placeholder).", "success")
    return redirect(url_for('admin.dashboard'))

