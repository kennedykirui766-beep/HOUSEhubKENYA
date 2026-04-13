from asyncio import Event
import base64
from datetime import datetime
from io import BytesIO
import json
from operator import or_
import os

from flask import Blueprint, current_app, flash, jsonify, render_template, request, redirect, url_for
from flask_login import login_required, current_user, logout_user

import pyotp
import qrcode as qr_code

from werkzeug.utils import secure_filename

from models.models import (
    Document, Booking, MaintenanceRequest, Message,
    House, Notification, Payment, User, Event
)

from extensions import db, csrf
from utils_delete import delete_user_and_dependents
import cloudinary.uploader
from flask import request, flash, redirect, url_for
from werkzeug.security import generate_password_hash
from flask_wtf import FlaskForm
from wtforms import TextAreaField, SelectField
from wtforms.validators import DataRequired



tenant_bp = Blueprint('tenant', __name__, url_prefix='/tenant')

@tenant_bp.route('/dashboard')
@login_required
def dashboard():
    # Ensure the user is a tenant
    if current_user.role != 'tenant':
        flash('Access restricted to tenants.', category='error')
        return redirect(url_for('auth.login'))

    # Fetch the tenant's active booking and associated house
    active_booking = Booking.query.filter_by(
        tenant_id=current_user.id, status='active'
    ).first()

    house = None
    landlord = None
    if active_booking:
        house = House.query.get(active_booking.house_id)
        if house and house.owner_id:
            landlord = User.query.filter_by(
                id=house.owner_id, role='landlord'
            ).first()

    # Fetch other required data
    bookings = Booking.query.filter_by(tenant_id=current_user.id).all()
    payments = Payment.query.filter_by(
        tenant_id=current_user.id
    ).order_by(Payment.date.desc()).all()
    maintenance_requests = MaintenanceRequest.query.filter_by(
        tenant_id=current_user.id
    ).order_by(MaintenanceRequest.date_submitted.desc()).all()
    notifications = Notification.query.filter_by(
        tenant_id=current_user.id
    ).order_by(Notification.date.desc()).all()
    events = Event.query.filter_by(tenant_id=current_user.id).all()

    open_requests_count = len([
        req for req in maintenance_requests
        if req.status.lower() in ['open', 'in progress']
    ])

    # Next payment
    next_payment = Payment.query.filter_by(
        tenant_id=current_user.id, status='Pending'
    ).order_by(Payment.due_date.asc()).first()

    # Payment chart data
    payment_labels = [p.date.strftime('%b %Y') for p in payments]
    payment_data = [p.amount for p in payments]
    dashboard_order = []
    if current_user.dashboard_order:
        try:
            parsed_order = json.loads(current_user.dashboard_order)
            if isinstance(parsed_order, list):
                dashboard_order = parsed_order
        except (TypeError, json.JSONDecodeError):
            dashboard_order = []

    return render_template(
        'tenant.html',
        property=house,               # renamed to match your template
        bookings=bookings,
        payments=payments,
        maintenance_requests=maintenance_requests,
        notifications=notifications,
        landlord=landlord,            # ✅ always available in template (or None)
        events=events,
        open_requests_count=open_requests_count,
        next_payment=next_payment,
        payment_labels=payment_labels,
        payment_data=payment_data,
        dashboard_order=dashboard_order
    )


@tenant_bp.route('/save_dashboard_order', methods=['POST'])
@login_required
def save_dashboard_order():
    if current_user.role != 'tenant':
        return jsonify({'message': 'Access restricted to tenants.'}), 403

    payload = request.get_json(silent=True) or {}
    order = payload.get('order', [])

    if not isinstance(order, list):
        return jsonify({'message': 'Invalid payload format.'}), 400

    cleaned_order = []
    for card_id in order:
        if isinstance(card_id, str):
            value = card_id.strip()
            if value:
                cleaned_order.append(value[:100])

    current_user.dashboard_order = json.dumps(cleaned_order)
    db.session.commit()
    return jsonify({'message': 'Dashboard order saved.', 'order': cleaned_order}), 200


# Make a booking for a house
@tenant_bp.route('/bookings/<int:house_id>')
@login_required
def bookings(house_id):
    booking = Booking(tenant_id=current_user.id, house_id=house_id, status='pending')
    db.session.add(booking)
    db.session.commit()
    return redirect(url_for('tenant.dashboard'))

import json
from sqlalchemy import or_
from sqlalchemy.orm import joinedload

from sqlalchemy.orm import joinedload
from sqlalchemy import or_
import json

@tenant_bp.route("/properties", methods=['GET'])
def properties():
    query = request.args.get('query', '').strip()
    is_guest = not current_user.is_authenticated

    # Base query with owner
    house_query = House.query.options(joinedload(House.owner))

    # Search
    if query:
        house_query = house_query.filter(
            or_(
                House.location.ilike(f'%{query}%'),
                House.title.ilike(f'%{query}%'),
                House.city.ilike(f'%{query}%'),
                House.property_type.ilike(f'%{query}%')
            )
        )

    houses = house_query.order_by(House.available.desc()).all()

    processed_houses = []

    for house in houses:
        images = []

        # ✅ Handle JSON or comma-separated string
        if house.image_urls:
            try:
                images = json.loads(house.image_urls)
                if not isinstance(images, list):
                    images = []
            except Exception:
                images = [
                    img.strip() for img in house.image_urls.split(",")
                    if img.strip()
                ]

        # ✅ Optimize Cloudinary images
        def optimize(url):
            if url and "res.cloudinary.com" in url:
                return url.replace("/upload/", "/upload/f_auto,q_auto/")
            return url

        images = [optimize(img) for img in images]

        # ✅ Default fallback image
        image_url = images[0] if images else url_for('static', filename='images/default-house.jpg')

        processed_houses.append({
            "id": house.id,
            "title": house.title,
            "location": house.location,
            "price": house.rent_amount,
            "bedrooms": house.bedrooms,
            "bathrooms": house.bathrooms,
            "image": image_url,
            "available": house.available,
            "owner": house.owner.name if house.owner else "Unknown"
        })

    return render_template(
        "tenant/properties.html",
        houses=processed_houses,
        query=query,
        is_guest=is_guest
    )

@tenant_bp.route('/upload_document', methods=['GET', 'POST'])
@login_required
def upload_document():

    if request.method == 'POST':

        if 'document' not in request.files:
            flash("No file part", "danger")
            return redirect(request.url)

        file = request.files['document']

        if file.filename == '':
            flash("No file selected", "danger")
            return redirect(request.url)

        try:
            # -------------------------
            # UPLOAD TO CLOUDINARY
            # -------------------------
            upload_result = cloudinary.uploader.upload(
                file,
                resource_type="auto",  # supports pdf, images, etc.
                folder="homehub/documents"
            )

            file_url = upload_result.get("secure_url")

            # -------------------------
            # SAVE TO DATABASE
            # -------------------------
            new_doc = Document(
                tenant_id=current_user.id,
                name=secure_filename(file.filename),
                file_url=file_url,
                uploaded_at=datetime.utcnow()
            )

            db.session.add(new_doc)
            db.session.commit()

            flash("Document uploaded successfully!", "success")
            return redirect(url_for('tenant.documents'))

        except Exception as e:
            print(e)
            flash("Upload failed. Try again.", "danger")
            return redirect(request.url)

    return render_template('tenant/upload_document.html')

# routes/tenant_routes.py

import cloudinary.uploader
from datetime import datetime
from flask import request, flash, redirect, url_for

@tenant_bp.route('/documents', methods=['GET', 'POST'])
@login_required
def documents():

    if request.method == 'POST':

        file = request.files.get('document')
        doc_name = request.form.get('name')

        if not file or file.filename == "":
            flash("Please select a file to upload.", "danger")
            return redirect(url_for('tenant.documents'))

        try:
            # -------------------------
            # UPLOAD TO CLOUDINARY
            # -------------------------
            upload_result = cloudinary.uploader.upload(
                file,
                resource_type="auto",  # allows pdf, images, etc.
                folder="homehub/documents"
            )

            file_url = upload_result.get("secure_url")

            # -------------------------
            # SAVE TO DATABASE
            # -------------------------
            new_doc = Document(
                tenant_id=current_user.id,
                name=doc_name if doc_name else file.filename,
                file_url=file_url,
                uploaded_at=datetime.utcnow()
            )

            db.session.add(new_doc)
            db.session.commit()

            flash("Document uploaded successfully!", "success")

        except Exception as e:
            print(e)
            flash("Upload failed. Try again.", "danger")

        return redirect(url_for('tenant.documents'))

    # -------------------------
    # FETCH DOCUMENTS
    # -------------------------
    tenant_documents = Document.query.filter_by(
        tenant_id=current_user.id
    ).all()

    return render_template('documents.html', documents=tenant_documents)


@tenant_bp.route('/submit_request', methods=['GET', 'POST'])
@login_required
def submit_request():

    # Get tenant's approved bookings
    bookings = Booking.query.filter_by(
        tenant_id=current_user.id,
        status='approved'
    ).all()

    if request.method == 'POST':
        issue = request.form.get('issue')
        house_id = request.form.get('house_id')

        if not issue or not house_id:
            flash("Please select a house and describe the issue.", "danger")
            return redirect(url_for('tenant.submit_request'))

        # Validate house safely
        house = House.query.get(house_id)
        if not house:
            flash("Selected property not found.", "danger")
            return redirect(url_for('tenant.submit_request'))

        # Create maintenance request
        request_obj = MaintenanceRequest(
            tenant_id=current_user.id,
            house_id=house.id,
            issue=issue,
            status="Open",
            date_submitted=datetime.utcnow()
        )

        db.session.add(request_obj)

        # Get landlord safely
        landlord = User.query.get(house.owner_id)

        if landlord:
            message = Message(
                sender_id=current_user.id,
                receiver_id=landlord.id,
                content=f"New maintenance request for {house.title}: {issue}"
            )
            db.session.add(message)

        db.session.commit()

        flash("Maintenance request sent to landlord!", "success")
        return redirect(url_for('tenant.dashboard'))

    return render_template('tenant/submit_request.html', bookings=bookings)


@tenant_bp.route('/pay_rent', methods=['GET', 'POST'])
@login_required
def pay_rent():

    # Only approved bookings
    bookings = Booking.query.filter_by(
        tenant_id=current_user.id,
        status='approved'
    ).all()

    if request.method == 'POST':

        house_id = request.form.get('house_id')
        payment_month = request.form.get('payment_month')

        house = House.query.get_or_404(house_id)

        # ✅ Get rent from house
        amount = house.rent_amount

        # ✅ Prevent duplicate payments
        existing = Payment.query.filter_by(
            tenant_id=current_user.id,
            house_id=house_id,
            payment_month=payment_month
        ).first()

        if existing:
            flash("You already paid for this month!", "warning")
            return redirect(url_for('tenant.pay_rent'))

        payment = Payment(
            tenant_id=current_user.id,
            house_id=house.id,
            amount=amount,
            payment_month=payment_month,
            date=datetime.utcnow().date(),
            status='Pending'
        )

        db.session.add(payment)
        db.session.commit()

        flash("Rent payment submitted!", "success")
        return redirect(url_for('tenant.dashboard'))

    return render_template('tenant/pay_rent.html', bookings=bookings)




@tenant_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    user = current_user

    if request.method == 'POST':

        # ----------------------
        # BASIC INFO UPDATE
        # ----------------------
        user.name = request.form.get('name')
        user.email = request.form.get('email')
        user.phone_number = request.form.get('phone_number')
        user.address = request.form.get('address')
        user.bio = request.form.get('bio')
        user.business_name = request.form.get('business_name')
        user.language = request.form.get('language')

        # ----------------------
        # NOTIFICATIONS
        # ----------------------
        user.email_notifications = True if request.form.get('email_notifications') == 'on' else False
        user.message_alerts = True if request.form.get('message_alerts') == 'on' else False

        # ----------------------
        # PROFILE PICTURE UPLOAD (CLOUDINARY)
        # ----------------------
        if 'profile_picture' in request.files:
            file = request.files['profile_picture']

            if file and file.filename != "":

                # Upload to Cloudinary
                upload_result = cloudinary.uploader.upload(
                    file,
                    folder="homehub/profile_pictures"
                )

                # Save secure URL
                user.profile_picture = upload_result.get("secure_url")

        # ----------------------
        # PASSWORD CHANGE
        # ----------------------
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        if new_password:
            if new_password == confirm_password:
                user.set_password(new_password)
            else:
                flash("Passwords do not match!", "danger")
                return redirect(url_for('tenant.profile'))

        db.session.commit()

        flash("Profile updated successfully!", "success")
        return redirect(url_for('tenant.profile'))

    return render_template('profile.html', tenant=user)


@tenant_bp.route('/delete_account', methods=['GET', 'POST'])
@login_required
def delete_account():
    if request.method == 'POST':
        user = current_user
        db.session.delete(user)
        db.session.commit()
        # After deletion, redirect to sign-in
        return redirect(url_for('auth.login'))

    return render_template(
        'shared/delete_account.html',
        back_url=url_for('tenant.profile'),
        post_url=url_for('tenant.delete_account')
    )

@tenant_bp.route('/feedback', methods=['GET', 'POST'])
@login_required
def feedback():
    if request.method == 'POST':
        feedback_text = request.form['feedback']
        # Save feedback to DB (you’ll need a Feedback model)
        # feedback = Feedback(tenant_id=current_user.id, content=feedback_text)
        # db.session.add(feedback)
        # db.session.commit()
        return redirect(url_for('tenant.dashboard'))
    
    return render_template('tenant_feedback.html')


@tenant_bp.route('/2fa_setup', methods=['GET', 'POST'])
@login_required
def twofa_setup():
    # Ensure the user is a tenant
    if current_user.role != 'tenant':
        flash('Access restricted to tenants.', category='error')
        return redirect(url_for('tenant.dashboard'))

    if request.method == 'POST':
        # Handle 2FA setup form submission
        verification_code = request.form.get('verification_code')
        secret = current_user.two_factor_secret  # Assume secret is stored in user model

        if not secret:
            flash('2FA setup session expired. Please try again.', category='error')
            return redirect(url_for('tenant.twofa_setup'))

        # Verify the provided code
        totp = pyotp.TOTP(secret)
        if totp.verify(verification_code):
            current_user.two_factor_enabled = True
            db.session.commit()
            flash('2FA successfully enabled!', category='success')
            return redirect(url_for('tenant.dashboard'))
        else:
            flash('Invalid verification code. Please try again.', category='error')

    # GET request: Generate and display 2FA secret and QR code
    if not current_user.two_factor_secret:
        # Generate a new TOTP secret
        secret = pyotp.random_base32()
        current_user.two_factor_secret = secret
        db.session.commit()
    else:
        secret = current_user.two_factor_secret

    # Generate QR code for authenticator app
    totp_uri = pyotp.totp.TOTP(secret).provisioning_uri(
        name=current_user.email,
        issuer_name='HomeHub'
    )
    qr = qr_code.QRCode(version=1, box_size=10, border=5)
    qr.add_data(totp_uri)
    qr.make(fit=True)
    img = qr.make_image(fill='black', back_color='white')
    buffered = BytesIO()
    img.save(buffered)
    qr_code_b64 = base64.b64encode(buffered.getvalue()).decode('utf-8')

    return render_template('2fa_setup.html', qr_code=qr_code_b64, secret=secret)

@tenant_bp.route('/move_out/<int:booking_id>', methods=['POST'])
@login_required
def move_out(booking_id):
    booking = Booking.query.filter_by(id=booking_id, tenant_id=current_user.id).first_or_404()
    booking.status = 'move_out_requested'
    db.session.commit()
    return redirect(url_for('tenant.dashboard'))


@tenant_bp.route("/book/<int:house_id>", methods=["POST"])
@login_required
def book_house(house_id):
    house = House.query.get_or_404(house_id)

    # Check availability
    if not house.available:
        flash("House is already booked.", "danger")
        return redirect(url_for("tenant.properties"))

    # Create booking
    booking = Booking(
        tenant_id=current_user.id,
        house_id=house.id,
        status="pending"
    )

    # Mark house as unavailable
    house.available = False

    db.session.add(booking)
    db.session.commit()

    flash("Booking request sent!", "success")
    return redirect(url_for("tenant.properties"))


# View all bookings
@tenant_bp.route('/all_bookings')
@login_required
def all_bookings():
    bookings = Booking.query.filter_by(tenant_id=current_user.id).all()

    bookings_data = [
        {
            "id": b.id,
            "status": b.status,
            "created_at": b.created_at,
            "amount": b.house.rent_amount,
            "house": {
                "name": b.house.title,
                "location": b.house.location,
                "images": json.loads(b.house.image_urls)  # if exists
            }
        }
        for b in bookings
    ]

    return render_template(
        'tenant/tenant_bookings.html',
        bookings=bookings_data
    )


@tenant_bp.route('/messages')
@login_required
def messages():
    if current_user.role != "tenant":
        flash("Access restricted to tenants.", "danger")
        return redirect(url_for("auth.login"))

    try:
        # ✅ Use receiver_id (NOT recipient_id)
        tenant_messages = Message.query.filter(
            or_(
                Message.sender_id == current_user.id,
                Message.receiver_id == current_user.id
            )
        ).order_by(Message.timestamp.desc()).all()

        return render_template("tenant/messages.html", messages=tenant_messages)

    except Exception as e:
        db.session.rollback()
        print("Error loading messages:", e)
        flash("Unable to load messages.", "danger")
        return redirect(url_for("tenant.dashboard"))


@tenant_bp.route('/compose_message', methods=['GET', 'POST'])
@login_required
def compose_message():
    # 🔍 Find active booking for tenant
    booking = Booking.query.filter_by(
        tenant_id=current_user.id,
        status='active'
    ).first()

    if not booking:
        flash("You do not have an active booking.", "danger")
        return redirect(url_for('tenant.dashboard'))

    # 🏠 Get property
    property = booking.property

    # 👨‍💼 Get landlord from property
    landlord = User.query.get(property.landlord_id)

    if request.method == 'POST':
        content = request.form.get('content')

        if not content:
            flash("Message cannot be empty.", "danger")
            return redirect(url_for('tenant.compose_message'))

        new_message = Message(
            sender_id=current_user.id,
            receiver_id=landlord.id,
            content=content,
            is_read=False
        )

        db.session.add(new_message)
        db.session.commit()

        flash("Message sent to your landlord!", "success")
        return redirect(url_for('tenant.messages'))

    return render_template(
        'tenant/compose_message.html',
        landlord=landlord
    )


# Contact service providers
@tenant_bp.route('/contact_providers')
@login_required
def contact_providers():
    service_providers = User.query.filter_by(role='service').all()
    return render_template(
        'tenant.html',
        bookings=[],
        houses=[],
        service_providers=service_providers
    )

# Chat with landlord
@tenant_bp.route('/chat/<int:landlord_id>', methods=['GET', 'POST'])
@login_required
def chat(landlord_id):
    if request.method == 'POST':
        message = Message(
            sender_id=current_user.id,
            receiver_id=landlord_id,
            content=request.form['message']
        )
        db.session.add(message)
        db.session.commit()

    messages = Message.query.filter(
        ((Message.sender_id == current_user.id) & (Message.receiver_id == landlord_id)) |
        ((Message.sender_id == landlord_id) & (Message.receiver_id == current_user.id))
    ).order_by(Message.timestamp.asc()).all()

    landlord = User.query.get(landlord_id)
    return render_template('chat.html', messages=messages, user=landlord)


# routes/tenant_routes.py

@tenant_bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    # Only tenants can access
    if current_user.role != 'tenant':
        flash("Access restricted to tenants.", "error")
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        # Example: update tenant profile settings
        current_user.name = request.form.get('name')
        current_user.email = request.form.get('email')
        db.session.commit()
        flash("Settings updated successfully.", "success")

    return render_template("tenant_settings.html", user=current_user)


@tenant_bp.route('/notifications')
def view_notifications():
    # Fetch notifications
    return render_template('tenant/notifications.html')


@tenant_bp.route('/receipt/<int:id>')
@login_required
def view_receipt(id):
    payment = Payment.query.filter_by(
        id=id,
        tenant_id=current_user.id
    ).first_or_404()

    return render_template('tenant/receipt.html', payment=payment)