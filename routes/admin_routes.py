from flask import Blueprint, render_template, redirect, request, url_for, flash
from flask_login import login_required, current_user
from models.models import User, House
from extensions import db

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

# --- Helpers ---
def is_admin():
    return current_user.is_authenticated and current_user.role == 'admin'

@admin_bp.before_request
def restrict_to_admin():
    if not is_admin():
        flash("Access denied. Admins only.")
        return redirect(url_for('auth.login'))

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
    return render_template('admin.html', users=users, houses=houses, stats=stats)

@admin_bp.route('/system_settings')
@login_required
def system_settings():
    return render_template('admin.system_settings')

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
    db.session.delete(user)
    db.session.commit()
    flash("User deleted.")
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
    db.session.delete(house)
    db.session.commit()
    flash("Property removed.")
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
    message = request.form.get("message")
    if not message:
        flash("Announcement message cannot be empty.", "danger")
        return redirect(url_for('admin.dashboard'))

    # Placeholder logic — later you can extend this to send emails/SMS/notifications
    flash(f"Announcement sent: {message}", "success")
    return redirect(url_for('admin.dashboard'))

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
        for user_id in ids:
            user = User.query.get(user_id)
            if user:
                db.session.delete(user)
        db.session.commit()
        flash(f"{len(ids)} user(s) deleted.", "success")

    elif action == "delete_properties":
        for house_id in ids:
            house = House.query.get(house_id)
            if house:
                db.session.delete(house)
        db.session.commit()
        flash(f"{len(ids)} property(ies) deleted.", "success")

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
        db.session.delete(user)
        db.session.commit()
        flash(f"User {user.username} deleted.", "success")

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

