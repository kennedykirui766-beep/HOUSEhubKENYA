from flask import Blueprint, render_template, redirect, request, url_for, flash, session
from flask_login import login_required, current_user
from sqlalchemy import inspect
import logging
from models.models import User, House, SystemUpdateSubscriber
from extensions import db, csrf
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
    return {
        'total_users': User.query.count(),
        'total_properties': House.query.count(),
        'total_transactions': 0,   # Placeholder
        'uptime': 99.5,            # Placeholder (% uptime)
        'api_response': 280,       # Placeholder (ms)
        'maintenance_total': 0,    # Placeholder
        'maintenance_open': 0,
        'maintenance_resolved': 0,
        'feedback_total': 0,
        'feedback_open': 0,
        'feedback_resolved': 0,
        'daily_logins': [5, 8, 12, 10, 7, 9, 14],  # Example
        'total_reports': 0
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
    # Render the existing platform settings template for system settings
    return render_template('platform_settings.html')

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

# --- Platform Settings ---
@admin_bp.route('/platform_settings',  methods=['GET', 'POST'])
@login_required
def platform_settings():
    settings = {
        "language": "English",
        "theme": "Light",
        "maintenance_mode": False
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

# --- Export Reports ---
@admin_bp.route('/export_reports')
@login_required
def export_reports():
    # Placeholder: Later you can generate CSV, Excel, or PDF
    flash("Reports exported successfully (placeholder).", "success")
    return redirect(url_for('admin.view_reports'))

# --- Download Audit Log ---
@admin_bp.route('/download_audit_log')
@login_required
def download_audit_log():
    # Placeholder: later we can stream a CSV/Excel/JSON file
    flash("Audit log downloaded successfully (placeholder).", "success")
    return redirect(url_for('admin.dashboard'))

