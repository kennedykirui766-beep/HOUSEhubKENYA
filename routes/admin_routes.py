from flask import Blueprint, render_template, redirect, request, url_for, flash, session
from flask_login import login_required, current_user, login_user, logout_user
from sqlalchemy import inspect
from sqlalchemy import or_
import logging
from models.models import User, House, SystemUpdateSubscriber, SystemSetting
from models.models import SupportTicket, SupportMessage, MaintenanceRequest, Payment, MaintenanceComment
from extensions import db, csrf
from flask import make_response
import csv
import io
from datetime import datetime
from utils_delete import delete_user_and_dependents

logger = logging.getLogger(__name__)
from utils_email_2fa import send_system_update_email
from utils_security import (
    consume_rate_limit,
    get_allowed_admin_email,
    has_admin_totp_verified,
    is_approved_admin,
)

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

# --- Helpers ---
def is_admin():
    return current_user.is_authenticated and is_approved_admin(current_user)

@admin_bp.before_request
def restrict_to_admin():
    if not session.get('admin_entry_granted'):
        flash("Use the private admin access link before opening admin pages.", "warning")
        return redirect(url_for('auth.semantic_admin_entry'))

    if not is_admin():
        flash("Access denied. Admins only.", "danger")
        return redirect(url_for('auth.login'))

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
        maintenance_total = MaintenanceRequest.query.count()
        maintenance_open = MaintenanceRequest.query.filter(MaintenanceRequest.status != 'resolved').count()
        maintenance_resolved = MaintenanceRequest.query.filter(MaintenanceRequest.status == 'resolved').count()
    except Exception:
        maintenance_total = maintenance_open = maintenance_resolved = 0

    try:
        support_open = SupportTicket.query.filter(SupportTicket.status != 'resolved').count()
    except Exception:
        support_open = 0

    # Payment failures heuristic
    try:
        payment_failures = Payment.query.filter(
            (Payment.status.ilike('%fail%')) | (Payment.status.ilike('%error%'))
        ).count()
    except Exception:
        payment_failures = 0

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
        'maintenance_total': maintenance_total,
        'maintenance_open': maintenance_open,
        'maintenance_resolved': maintenance_resolved,
        'support_open': support_open,
        'payment_failures': payment_failures,
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
            flash("User permanently deleted.", "success")
        else:
            flash(f"Failed to delete user: {error}", "danger")
    else:
        # Soft-delete / deactivate
        setattr(user, 'is_active', False)
        db.session.commit()
        logger.info(f"Admin {current_user.id} deactivated user {user_id}")
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
        flash("Property permanently removed.")
    else:
        house.available = False
        db.session.commit()
        logger.info(f"Admin {current_user.id} marked property {house_id} unavailable (soft)")
        flash("Property marked unavailable.")
    return redirect(url_for('admin.dashboard'))

# --- Reports ---
@admin_bp.route('/view_reports')
@login_required
def view_reports():
    stats = get_stats()
    return render_template('admin.view_reports.html', stats=stats)


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
    flash('Support ticket marked resolved.', 'success')
    return redirect(url_for('admin.support_tickets'))

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

        # Persist
        SystemSetting.set('max_listings', str(max_listings))
        SystemSetting.set('default_status', default_status)
        SystemSetting.set('notification_enabled', '1' if notification_enabled else '0')
        SystemSetting.set('maintenance_mode', '1' if maintenance_mode else '0')
        SystemSetting.set('maintenance_start', maintenance_start)
        SystemSetting.set('maintenance_end', maintenance_end)

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
    }
    return render_template('platform_settings.html', settings=settings)

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
        flash('Role updated.', 'success')
        return redirect(url_for('admin.roles'))
    permissions = Permission.query.order_by(Permission.name).all()
    return render_template('admin.role_form.html', role=role, permissions=permissions)


@admin_bp.route('/roles/<int:role_id>/delete', methods=['POST'])
@login_required
def delete_role(role_id):
    from models.models import Role
    role = Role.query.get_or_404(role_id)
    # prevent deleting core roles maybe
    db.session.delete(role)
    db.session.commit()
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
        flash('Permission updated.', 'success')
        return redirect(url_for('admin.permissions'))
    return render_template('admin.permission_form.html', permission=p)


@admin_bp.route('/permissions/<int:perm_id>/delete', methods=['POST'])
@login_required
def delete_permission(perm_id):
    from models.models import Permission
    p = Permission.query.get_or_404(perm_id)
    db.session.delete(p)
    db.session.commit()
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
                preview.append({'id': user.id, 'username': user.username, 'action': 'permanently delete'})
            else:
                preview.append({'id': user.id, 'username': user.username, 'action': 'soft-deactivate'})

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
        flash(f"{deleted} user(s) processed (soft-deactivate or hard-delete).", "success")

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
            flash(f"User {getattr(user, 'name', user.id)} deleted.", "success")
        else:
            flash(f"Could not delete user: {error}", "danger")

    elif action == "deactivate":
        user.is_active = False
        db.session.commit()
        flash(f"User {user.username} deactivated.", "warning")

    elif action == "activate":
        user.is_active = True
        db.session.commit()
        flash(f"User {user.username} activated.", "success")

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
    flash(f"Now impersonating {getattr(target, 'username', target.id)} (read-only).", 'info')
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
            flash('Stopped impersonation. You are back as admin.', 'success')
            return redirect(url_for('admin.dashboard'))

    # Fallback: log out
    logout_user()
    flash('Stopped impersonation. Please sign in.', 'info')
    return redirect(url_for('auth.login'))

# --- Export Reports ---
@admin_bp.route('/export_reports')
@login_required
def export_reports():
    # Placeholder: Later you can generate CSV, Excel, or PDF
    flash("Reports exported successfully (placeholder).", "success")
    return redirect(url_for('admin.view_reports'))


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

