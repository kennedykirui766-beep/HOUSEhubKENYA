from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError
from sqlalchemy import inspect
from models.models import House, SystemUpdateSubscriber, SupportMessage, SupportTicket
from extensions import db, csrf
from utils_email_2fa import send_support_contact_email, verify_email_format

main_bp = Blueprint('main', __name__)

import json


@main_bp.route('/api/live-chat/support', methods=['POST'])
@csrf.exempt
@login_required
def live_chat_support_escalate():
    """Escalate a live-chat command message to the support team."""
    if current_user.role not in ['tenant', 'landlord']:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

    payload = request.get_json(silent=True) or {}
    raw_message = (payload.get('message') or '').strip()
    source = (payload.get('source') or 'live_chat_command').strip()[:50]

    name = (payload.get('name') or '').strip() or (current_user.name or '').strip()
    email = (payload.get('email') or '').strip() or (current_user.email or '').strip()
    phone = (getattr(current_user, 'phone_number', None) or '').strip()
    role = (current_user.role or '').strip()

    if not raw_message:
        return jsonify({'success': False, 'error': 'Message is required'}), 400
    if not name or not email:
        return jsonify({'success': False, 'error': 'Name and email are required'}), 400
    if not verify_email_format(email):
        return jsonify({'success': False, 'error': 'Invalid email format'}), 400

    support_text = f"[via {source}] {raw_message}"

    try:
        ticket = SupportTicket(
            user_id=current_user.id,
            subject=f"Live chat escalation from {name}",
            description=support_text,
            status='open'
        )
        db.session.add(ticket)

        support_msg = SupportMessage(
            full_name=name,
            email=email,
            phone=phone,
            role=role,
            message=support_text,
            user_id=current_user.id
        )
        db.session.add(support_msg)
        db.session.commit()

        try:
            from services.notification import enqueue_support_email
            enqueue_support_email(
                full_name=name,
                sender_email=email,
                phone=phone,
                role=role,
                message=support_text,
            )
        except Exception:
            main_bp.logger.exception('Failed to enqueue live-chat support email')

        return jsonify({'success': True, 'ticket_id': ticket.id})
    except Exception:
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Failed to create support ticket'}), 500


@main_bp.route('/api/live-chat/support/status/<int:ticket_id>', methods=['GET'])
@login_required
def live_chat_support_status(ticket_id):
    """Return support ticket status for the current authenticated user."""
    if current_user.role not in ['tenant', 'landlord']:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

    ticket = SupportTicket.query.get(ticket_id)
    if not ticket or ticket.user_id != current_user.id:
        return jsonify({'success': False, 'error': 'Ticket not found'}), 404

    return jsonify({
        'success': True,
        'ticket': {
            'id': ticket.id,
            'subject': ticket.subject,
            'status': ticket.status,
            'created_at': ticket.created_at.isoformat() if ticket.created_at else None,
            'updated_at': ticket.updated_at.isoformat() if ticket.updated_at else None,
        }
    })


@main_bp.route('/api/live-chat/support/recent', methods=['GET'])
@login_required
def live_chat_support_recent():
    """Return recent support tickets for the current authenticated user."""
    if current_user.role not in ['tenant', 'landlord']:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

    try:
        limit = int(request.args.get('limit', 5))
    except (TypeError, ValueError):
        limit = 5
    limit = max(1, min(limit, 10))

    tickets = (
        SupportTicket.query
        .filter_by(user_id=current_user.id)
        .order_by(SupportTicket.created_at.desc())
        .limit(limit)
        .all()
    )

    return jsonify({
        'success': True,
        'tickets': [
            {
                'id': t.id,
                'status': t.status,
                'subject': t.subject,
                'created_at': t.created_at.isoformat() if t.created_at else None,
            }
            for t in tickets
        ]
    })

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
def contact():
    if request.method == 'POST':
        full_name = (request.form.get('full_name') or '').strip()
        email = (request.form.get('email') or '').strip()
        phone = (request.form.get('phone') or '').strip()
        role = (request.form.get('role') or '').strip()
        message = (request.form.get('message') or '').strip()

        if not full_name or not email or not message:
            flash('Please provide your name, email, and message.', 'danger')
            return redirect(url_for('main.contact'))

        if send_support_contact_email(full_name, email, phone, role, message):
            flash('Your message has been sent to support.', 'success')
            return redirect(url_for('main.contact'))

        flash('Unable to send your message right now. Please try again later.', 'danger')
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
    return redirect(url_for('main.index') + '#newsletter')

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
    # Service-provider help removed — redirect to general help
    flash("Service provider help is no longer available.", "info")
    return redirect(url_for('main.help'))


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
    name = (request.form.get('name') or '').strip()
    email = (request.form.get('email') or '').strip().lower()
    topics = request.form.getlist('newsletter_topics')

    allowed_topics = {
        'platform_updates',
        'security_alerts',
        'maintenance_notices',
        'new_features',
    }
    selected_topics = [topic for topic in topics if topic in allowed_topics]

    if not email:
        flash('No email provided', 'danger')
        return redirect(url_for('main.index'))

    if not verify_email_format(email):
        flash('Please provide a valid email address.', 'danger')
        return redirect(url_for('main.index'))

    if not selected_topics:
        flash('Please select at least one newsletter category.', 'danger')
        return redirect(url_for('main.index') + '#newsletter')

    # Keep feature functional even when Alembic history is out of sync.
    if not inspect(db.engine).has_table('system_update_subscriber'):
        db.create_all()

    existing = SystemUpdateSubscriber.query.filter_by(email=email).first()
    if existing:
        existing.is_active = True
        existing.name = name or existing.name
        existing.topics = ','.join(selected_topics)
        db.session.commit()
        flash('Your newsletter preferences were updated.', 'success')
        return redirect(url_for('main.index'))

    subscriber = SystemUpdateSubscriber(
        name=name or None,
        email=email,
        topics=','.join(selected_topics),
        is_active=True,
    )
    db.session.add(subscriber)
    try:
        db.session.commit()
        flash('Subscribed successfully for system updates.', 'success')
    except IntegrityError:
        db.session.rollback()
        flash('This email is already subscribed.', 'info')
    except Exception:
        db.session.rollback()
        flash('Could not complete subscription. Please try again.', 'danger')

    return redirect(url_for('main.index'))