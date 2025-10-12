from flask import Blueprint, current_app, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from models.models import ServiceProvider, ServiceRequest, Appointment, Review, User
from extensions import db
from sqlalchemy import func, extract
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
import os

service_provider_bp = Blueprint('service_provider', __name__, url_prefix='/service_provider')

@service_provider_bp.route('/dashboard')
@login_required
def dashboard():
    # Get service provider profile
    provider = ServiceProvider.query.filter_by(user_id=current_user.id).first()
    
    if not provider:
        flash('Please complete your service provider profile first.', 'warning')
        return redirect(url_for('service_provider.profile'))
    
    # Get counts
    pending_requests_count = ServiceRequest.query.filter_by(
        service_provider_id=provider.id, 
        status='pending'
    ).count()
    
    completed_jobs_count = ServiceRequest.query.filter_by(
        service_provider_id=provider.id, 
        status='completed'
    ).count()
    
    # Get monthly earnings
    current_month = datetime.now().month
    current_year = datetime.now().year
    monthly_earnings = db.session.query(
        func.sum(ServiceRequest.amount)
    ).filter(
        ServiceRequest.service_provider_id == provider.id,
        ServiceRequest.status == 'completed',
        extract('month', ServiceRequest.completed_at) == current_month,
        extract('year', ServiceRequest.completed_at) == current_year
    ).scalar() or 0
    
    # Get average rating
    average_rating = db.session.query(
        func.avg(Review.rating)
    ).filter_by(service_provider_id=provider.id).scalar() or 0
    
    # Get recent requests
    recent_requests = ServiceRequest.query.filter_by(
        service_provider_id=provider.id
    ).order_by(ServiceRequest.created_at.desc()).limit(5).all()
    
    # Get upcoming appointments
    upcoming_appointments = Appointment.query.filter(
        Appointment.service_provider_id == provider.id,
        Appointment.date >= datetime.now()
    ).order_by(Appointment.date).limit(5).all()
    
    # Get recent reviews
    recent_reviews = Review.query.filter_by(
        service_provider_id=provider.id
    ).order_by(Review.created_at.desc()).limit(3).all()
    
    # Get earnings data for chart
    earnings_labels = []
    earnings_data = []
    
    # Get data for the last 30 days
    for i in range(30, 0, -1):
        date = datetime.now() - timedelta(days=i)
        earnings_labels.append(date.strftime('%b %d'))
        
        daily_earnings = db.session.query(
            func.sum(ServiceRequest.amount)
        ).filter(
            ServiceRequest.service_provider_id == provider.id,
            ServiceRequest.status == 'completed',
            func.date(ServiceRequest.completed_at) == date.date()
        ).scalar() or 0
        
        earnings_data.append(float(daily_earnings))
    
    # Get notifications (placeholder - in a real app, this would come from a notifications table)
    notifications = []
    
    return render_template(
        'service_provider_dashboard.html',
        pending_requests_count=pending_requests_count,
        completed_jobs_count=completed_jobs_count,
        monthly_earnings=monthly_earnings,
        average_rating=average_rating,
        recent_requests=recent_requests,
        upcoming_appointments=upcoming_appointments,
        recent_reviews=recent_reviews,
        earnings_labels=earnings_labels,
        earnings_data=earnings_data,
        notifications=notifications
    )

@service_provider_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    # Check if ServiceProvider already exists for current user
    provider = ServiceProvider.query.filter_by(user_id=current_user.id).first()

    # If not, create a new ServiceProvider record safely
    if not provider:
        provider = ServiceProvider(
            user_id=current_user.id,
            name=current_user.name or "Unnamed Provider",
            phone=current_user.phone_number or "Not provided",  # <-- fixed
            service="Not specified",                            # <-- required
            description="No description",                       # <-- required
            service_type="General Services",
            location="Not specified",
            available=True
        )
        db.session.add(provider)
        db.session.commit()

    # Handle form submission
    if request.method == 'POST':
        # Update profile information safely
        provider.name = request.form.get('name') or provider.name
        provider.phone = request.form.get('phone') or provider.phone          # <-- fixed to match form
        provider.service = request.form.get('services') or provider.service
        provider.description = request.form.get('description') or provider.description
        provider.service_type = request.form.get('service_type') or provider.service_type
        provider.location = request.form.get('location') or provider.location
        provider.available = 'available' in request.form
        provider.working_hours = request.form.get('working_hours') or provider.working_hours

        # Commit updates to the database
        try:
            db.session.commit()
            flash("Profile updated successfully.", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"An error occurred: {str(e)}", "error")

        return redirect(url_for('service_provider.profile'))

    # Render profile template
    return render_template(
        'service_provider/profile.html',
        provider=provider,
        current_user=current_user
    )

@service_provider_bp.route('/change_password', methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        # Make sure all fields are filled
        if not current_password or not new_password or not confirm_password:
            flash("All password fields are required.", "danger")
            return redirect(url_for('service_provider.account_settings'))

        # Make sure the user has a stored password
        if not current_user.password_hash:
            flash("Your account has no password set. Please contact support.", "danger")
            return redirect(url_for('service_provider.account_settings'))

        # Verify current password
        if not check_password_hash(current_user.password_hash, current_password):
            flash("Current password is incorrect.", "danger")
            return redirect(url_for('service_provider.account_settings'))

        # Verify new passwords match
        if new_password != confirm_password:
            flash("New passwords do not match.", "danger")
            return redirect(url_for('service_provider.account_settings'))

        # Update password safely
        current_user.password_hash = generate_password_hash(new_password)
        db.session.commit()

        flash("Password updated successfully!", "success")
        return redirect(url_for('service_provider.account_settings'))

    # If GET, just show the settings page (or a change password form)
    return render_template("service_provider/change_password.html")


@service_provider_bp.route('/toggle_availability', methods=['POST'])
@login_required
def toggle_availability():
    data = request.get_json()
    available = data.get('available', False)
    
    provider = ServiceProvider.query.filter_by(user_id=current_user.id).first()
    if provider:
        provider.available = available
        db.session.commit()
        return jsonify({'success': True})
    
    return jsonify({'success': False}), 400

@service_provider_bp.route('/earnings_data')
@login_required
def earnings_data():
    period = request.args.get('period', 'month')
    provider = ServiceProvider.query.filter_by(user_id=current_user.id).first()
    
    if not provider:
        return jsonify({'labels': [], 'values': []})
    
    labels = []
    values = []
    
    if period == 'week':
        # Get data for the last 7 days
        for i in range(7, 0, -1):
            date = datetime.now() - timedelta(days=i)
            labels.append(date.strftime('%a'))
            
            daily_earnings = db.session.query(
                func.sum(ServiceRequest.amount)
            ).filter(
                ServiceRequest.service_provider_id == provider.id,
                ServiceRequest.status == 'completed',
                func.date(ServiceRequest.completed_at) == date.date()
            ).scalar() or 0
            
            values.append(float(daily_earnings))
    
    elif period == 'month':
        # Get data for the last 30 days
        for i in range(30, 0, -1):
            date = datetime.now() - timedelta(days=i)
            labels.append(date.strftime('%b %d'))
            
            daily_earnings = db.session.query(
                func.sum(ServiceRequest.amount)
            ).filter(
                ServiceRequest.service_provider_id == provider.id,
                ServiceRequest.status == 'completed',
                func.date(ServiceRequest.completed_at) == date.date()
            ).scalar() or 0
            
            values.append(float(daily_earnings))
    
    elif period == 'year':
        # Get data for the last 12 months
        for i in range(12, 0, -1):
            date = datetime.now() - timedelta(days=30*i)
            labels.append(date.strftime('%b %Y'))
            
            monthly_earnings = db.session.query(
                func.sum(ServiceRequest.amount)
            ).filter(
                ServiceRequest.service_provider_id == provider.id,
                ServiceRequest.status == 'completed',
                extract('month', ServiceRequest.completed_at) == date.month,
                extract('year', ServiceRequest.completed_at) == date.year
            ).scalar() or 0
            
            values.append(float(monthly_earnings))
    
    return jsonify({'labels': labels, 'values': values})

# Additional routes for other dashboard pages would go here
@service_provider_bp.route('/requests')
@login_required
def requests():
    # Implementation for service requests page
    return render_template('service_provider_requests.html')

@service_provider_bp.route('/schedule')
@login_required
def schedule():
    # Implementation for schedule page
    return render_template('service_provider_schedule.html')

@service_provider_bp.route('/earnings')
@login_required
def earnings():
    # Implementation for earnings page
    return render_template('service_provider_earnings.html')

@service_provider_bp.route('/reviews')
@login_required
def reviews():
    # Implementation for reviews page
    return render_template('service_provider_reviews.html')

# Main Settings (hub page with all setting options)
@service_provider_bp.route("/settings")
@login_required
def settings():
    return render_template("service_provider/settings.html")

# Account Settings (detailed page for account updates)
@service_provider_bp.route("/account_settings")
@login_required
def account_settings():
    return render_template("service_provider/account_settings.html")


@service_provider_bp.route("/notification_settings")
@login_required
def notification_settings():
    return render_template("service_provider/notification_settings.html")


# Privacy Settings
@service_provider_bp.route("/privacy_settings")
@login_required
def privacy_settings():
    return render_template("service_provider/privacy_settings.html")

# Security Settings
@service_provider_bp.route("/security_settings")
@login_required
def security_settings():
    return render_template("service_provider/security_settings.html")

# Connected Accounts
@service_provider_bp.route("/connected_accounts")
@login_required
def connected_accounts():
    return render_template("service_provider/connected_accounts.html")

# Preferences
@service_provider_bp.route("/preferences")
@login_required
def preferences():
    return render_template("service_provider/preferences.html")

# Two-Factor Authentication Settings
@service_provider_bp.route("/two_factor")
@login_required
def two_factor():
    return render_template("service_provider/two_factor.html")

# Download account data (privacy/GDPR export)
@service_provider_bp.route("/download_data")
@login_required
def download_data():
    # In real apps, you might generate a ZIP or JSON export of user data
    return render_template("service_provider/download_data.html")

# Delete Account
@service_provider_bp.route("/delete_account", methods=["GET", "POST"])
@login_required
def delete_account():
    if request.method == "POST":
        # ⚠️ Example: Permanently delete the current user's account
        # You may want to add a confirmation step before this
        user = current_user
        db.session.delete(user)
        db.session.commit()
        flash("Your account has been deleted successfully.", "success")
        return redirect(url_for("main.index"))  # redirect to homepage after deletion

    return render_template("service_provider/delete_account.html")

@service_provider_bp.route('/browse_jobs')
@login_required
def browse_jobs():
    # load jobs from DB
    jobs = Job.query.all() # pyright: ignore[reportUndefinedVariable]
    return render_template("service_provider/browse_jobs.html", jobs=jobs)
