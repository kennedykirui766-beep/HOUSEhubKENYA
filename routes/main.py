from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import current_user, login_required
from models.models import House, SupportMessage
from extensions import db

main_bp = Blueprint('main', __name__)

import json

@main_bp.route('/')
@main_bp.route('/index')
def index():
    houses = House.query.all()

    # ✅ Convert JSON string → list for each house
    for h in houses:
        try:
            h.image_list = json.loads(h.image_urls) if h.image_urls else []
        except Exception:
            h.image_list = []

    return render_template('index.html', houses=houses)

@main_bp.route('/about')
def about():
    return render_template('about.html')


@main_bp.route('/contact', methods=['GET', 'POST'])
@login_required
def contact():
    if request.method == 'POST':
        full_name = request.form.get('fullName')
        email = request.form.get('email')
        phone = request.form.get('phone')
        role = request.form.get('role')
        message = request.form.get('message')

        # Save to database
        new_message = SupportMessage(
            full_name=full_name,
            email=email,
            phone=phone,
            role=role,
            message=message,
            user_id=current_user.id
        )

        db.session.add(new_message)
        db.session.commit()

        flash("Message sent successfully!", "success")
        return redirect(url_for('main.contact'))

    return render_template('contact.html')

@main_bp.route('/terms')
def terms():
    return render_template('terms.html')

@main_bp.route('/privacy')
def privacy():
    return render_template('privacy.html')

@main_bp.route('/accessibility')
def accessibility():
    return render_template('accessibility.html')

@main_bp.route('/subscribe')
def subscribe():
    return render_template('subscribe.html')

@main_bp.route('/help')
def help():
    return render_template('help.html')

@main_bp.route('/help/search_results')
def help_search_results():
    query = request.args.get('q')
    # maybe search FAQs or docs here
    results = []
    return render_template('help_search_results.html', query=query, results=results)

# Landlord Help Page
@main_bp.route('/help/landlord')
def help_landlord():
    return render_template('help_landlord.html')


# Tenant Help Page
@main_bp.route('/help/tenant')
def help_tenant():
    return render_template('help_tenant.html')


# Service Provider Help Page
@main_bp.route('/help/service-provider')
def help_service_provider():
    return render_template('help_service_provider.html')


# Admin Help Page
@main_bp.route('/help/admin')
def help_admin():
    return render_template('help_admin.html')

@main_bp.route('/help/general')
def help_general():
    return render_template('help_general.html')



@main_bp.route('/how-it-works')
def how_it_works_general():
    return render_template('how_it_works.html')


@main_bp.route('/how-it-works/landlord')
def how_it_works_landlord():
    return render_template('how_it_works_landlord.html')

@main_bp.route('/how-it-works/tenant')
def how_it_works_tenant():
    return render_template('how_it_works_tenant.html')

@main_bp.route('/how-it-works/provider')
def how_it_works_provider():
    return render_template('how_it_works_provider.html')

@main_bp.route('/how-it-works/admin')
def how_it_works_admin():
    return render_template('how_it_works_admin.html')

@main_bp.route('/how-it-works/<role>')
def how_it_works(role):
    return render_template(f"how_it_works_{role}.html")



@main_bp.route('/subscribe', methods=['POST'])
def subscribe_post():
    email = request.form.get('email')
    if email:
        flash(f'Subscribed successfully with {email}', 'success')
    else:
        flash('No email provided', 'danger')
    return redirect(url_for('main.index'))