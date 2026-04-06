import os
import logging
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from werkzeug.security import check_password_hash, generate_password_hash
from flask_login import login_required, current_user
from extensions import db, csrf
from werkzeug.utils import secure_filename
from datetime import datetime
from extensions import db, csrf
from models.models import Message, PaymentLink, User, House, Booking, Payment, MaintenanceRequest, ServiceProvider
import cloudinary.uploader
import json


# Logging setup
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Blueprint setup
landlord_bp = Blueprint("landlord", __name__, url_prefix="/landlord")

# ---------------- Landlord Dashboard ----------------
@landlord_bp.route("/dashboard")
@login_required
def dashboard():
    if current_user.role != "landlord":
        flash("Access denied.", "danger")
        return redirect(url_for("main.index"))

    houses = House.query.filter_by(owner_id=current_user.id).all()
    tenants = (
        db.session.query(User, Booking, House)
        .join(Booking, Booking.tenant_id == User.id)
        .join(House, Booking.house_id == House.id)
        .filter(User.role == "tenant", House.owner_id == current_user.id)
        .all()
    )
    return render_template("landlord/dashboard.html", houses=houses, tenants=tenants, stats={})


# ---------------- Manage Properties ----------------
import json

@landlord_bp.route("/properties")
@login_required
def properties():
    if current_user.role != "landlord":
        flash("Access denied.", "danger")
        return redirect(url_for("main.index"))

    properties = House.query.filter_by(owner_id=current_user.id).all()

    # ✅ Convert JSON string → list
    for p in properties:
        try:
            p.image_list = json.loads(p.image_urls) if p.image_urls else []
        except Exception:
            p.image_list = []

    return render_template(
        "landlord/properties.html",
        properties=properties,
        stats={}
    )


# ---------------- Add Property ----------------


@landlord_bp.route("/properties/add", methods=["GET", "POST"])
@login_required
def add_property():
    if current_user.role != "landlord":
        return {"message": "Access denied"}, 403

    if request.method == "POST":
        try:
            # ---- Basic Info ----
            title = request.form.get("title")
            description = request.form.get("description")
            property_type = request.form.get("property_type")

            # ---- Location ----
            address_line1 = request.form.get("address_line1")
            address_line2 = request.form.get("address_line2")
            city = request.form.get("city")
            state_province = request.form.get("state_province")
            postal_code = request.form.get("postal_code")
            country = request.form.get("country")

            location = f"{address_line1}, {city}, {country}"

            # ---- Pricing ----
            rent_amount = float(request.form.get("rent_amount") or 0)
            security_deposit = float(request.form.get("security_deposit") or 0)
            lease_term = request.form.get("lease_term")

            availability_date = request.form.get("availability_date")
            availability_date = datetime.strptime(availability_date, "%Y-%m-%d") if availability_date else None

            # ---- Specifications ----
            bedrooms = int(request.form.get("bedrooms") or 0)
            bathrooms = float(request.form.get("bathrooms") or 0)
            size = request.form.get("square_footage")

            # ---- Features ----
            parking_availability = request.form.get("parking_availability")
            furnished_status = request.form.get("furnished_status")

            utilities = request.form.getlist("utilities")
            amenities = request.form.getlist("amenities")

            utilities = ",".join(utilities)
            amenities = ",".join(amenities)

            # ---- Policies ----
            pets_allowed = request.form.get("pets_allowed")
            pet_restrictions = request.form.get("pet_restrictions")
            smoking_policy = request.form.get("smoking_policy")

            accessibility_features = request.form.getlist("accessibility_features")
            accessibility_features = ",".join(accessibility_features)

            # ---- Images Upload (Cloudinary) ----
            image_files = request.files.getlist("images")
            image_urls = []

            import cloudinary.uploader

            for image in image_files:
                if image and image.filename:
                    try:
                        result = cloudinary.uploader.upload(
                            image,
                            folder="homehub/properties",
                            resource_type="image"
                        )
                        image_urls.append(result.get("secure_url"))
                    except Exception as upload_error:
                        print("Cloudinary upload failed:", upload_error)

            image_urls_json = json.dumps(image_urls)

            # ---- Create House ----
            house = House(
                title=title,
                description=description,
                category=property_type,
                location=location,

                address_line1=address_line1,
                address_line2=address_line2,
                city=city,
                state_province=state_province,
                postal_code=postal_code,
                country=country,

                rent_amount=rent_amount,
                security_deposit=security_deposit,
                lease_term=lease_term,
                availability_date=availability_date,

                property_type=property_type,
                bedrooms=bedrooms,
                bathrooms=bathrooms,
                size=size,

                parking_availability=parking_availability,
                furnished_status=furnished_status,
                utilities=utilities,
                amenities=amenities,

                pets_allowed=pets_allowed,
                pet_restrictions=pet_restrictions,
                smoking_policy=smoking_policy,
                accessibility_features=accessibility_features,

                image_urls=image_urls_json,
                owner_id=current_user.id,
            )

            db.session.add(house)
            db.session.commit()

            flash("Property added successfully!", "success")
            return redirect(url_for("landlord.properties"))

        except Exception as e:
            db.session.rollback()
            return {"message": str(e)}, 500

    return render_template("landlord/add_property.html", stats={})

# ---------------- Manage Tenants ----------------
@landlord_bp.route("/tenants")
@login_required
def tenants():
    if current_user.role != "landlord":
        flash("Access denied.", "danger")
        return redirect(url_for("main.index"))

    # Get all houses owned by landlord
    houses = House.query.filter_by(owner_id=current_user.id).all()

    # Collect all bookings for those houses
    bookings = (
        Booking.query
        .join(House)
        .filter(House.owner_id == current_user.id)
        .all()
    )

    tenants_data = []

    for booking in bookings:
        tenant = booking.tenant  # 🔥 via relationship
        house = booking.house

        tenants_data.append({
            "tenant_id": tenant.id,
            "tenant_name": tenant.name,
            "email": tenant.email,
            "phone": tenant.phone_number,
            "profile_picture": tenant.profile_picture,

            "house_id": house.id,
            "house_title": house.title,
            "house_location": house.location,
            "rent_amount": house.rent_amount,
            "security_deposit": house.security_deposit,

            "booking_id": booking.id,
            "status": booking.status,
            "lease_start": booking.lease_start_date,
            "lease_end": booking.lease_end_date,
            "created_at": booking.created_at,
        })

    # Optional: Stats
    stats = {
        "total_tenants": len({t["tenant_id"] for t in tenants_data}),
        "total_bookings": len(tenants_data),
        "approved": len([b for b in bookings if b.status == "approved"]),
        "pending": len([b for b in bookings if b.status == "pending"]),
        "rejected": len([b for b in bookings if b.status == "rejected"]),
    }

    return render_template(
        "landlord/tenants.html",
        tenants=tenants_data,
        stats=stats
    )


@landlord_bp.route("/api/generate-payment-link", methods=["POST"])
@login_required
def api_generate_payment_link():
    data = request.get_json()
    booking_id = data.get("booking_id")

    booking = Booking.query.get_or_404(booking_id)

    if booking.house.owner_id != current_user.id:
        return jsonify({"error": "Unauthorized"}), 403

    import uuid
    token = str(uuid.uuid4())

    link = PaymentLink(
        token=token,
        landlord_id=current_user.id,
        house_id=booking.house_id,
        amount=booking.deposit_amount,
        status="pending"
    )

    db.session.add(link)
    db.session.commit()

    payment_url = url_for("payments.pay", token=token, _external=True)

    return jsonify({
        "success": True,
        "payment_url": payment_url
    })

# ---------------- Payments ----------------
@landlord_bp.route("/payments")
@login_required
def payments():
    if current_user.role != "landlord":
        flash("Access denied.", "danger")
        return redirect(url_for("main.index"))

    payments = (
        db.session.query(Payment, User, House)
        .join(User, Payment.tenant_id == User.id)
        .join(Booking, Booking.tenant_id == User.id)
        .join(House, Booking.house_id == House.id)
        .filter(House.owner_id == current_user.id)
        .all()
    )
    return render_template("landlord/payments.html", payments=payments, stats={})


# ---------------- Maintenance Requests ----------------
@landlord_bp.route("/maintenance")
@login_required
def maintenance():
    if current_user.role != "landlord":
        flash("Access denied.", "danger")
        return redirect(url_for("main.index"))

    requests = (
        db.session.query(MaintenanceRequest, User, House)
        .join(User, MaintenanceRequest.tenant_id == User.id)
        .join(Booking, Booking.tenant_id == User.id)
        .join(House, Booking.house_id == House.id)
        .filter(House.owner_id == current_user.id)
        .all()
    )
    return render_template("landlord/maintenance.html", requests=requests, stats={})


# ---------------- Service Providers ----------------
@landlord_bp.route("/service-providers")
@login_required
def service_providers():
    if current_user.role != "landlord":
        flash("Access denied.", "danger")
        return redirect(url_for("main.index"))

    providers = ServiceProvider.query.all()
    return render_template("landlord/service_providers.html", providers=providers, stats={})


# ---------------- Reports ----------------
@landlord_bp.route("/reports")
@login_required
def reports():
    if current_user.role != "landlord":
        flash("Access denied.", "danger")
        return redirect(url_for("main.index"))
    return render_template("landlord/reports.html", stats={})


# ---------------- Edit Property ----------------

@landlord_bp.route("/properties/<int:property_id>/edit", methods=["GET", "POST"])
@login_required
def edit_property(property_id):
    if current_user.role != "landlord":
        flash("Access denied.", "danger")
        return redirect(url_for("main.index"))

    house = House.query.filter_by(
        id=property_id,
        owner_id=current_user.id
    ).first_or_404()

    if request.method == "POST":
        # ---- BASIC INFO ----
        house.title = request.form.get("title")
        house.description = request.form.get("description")
        house.property_type = request.form.get("property_type")
        house.category = house.property_type

        # ---- LOCATION ----
        house.address_line1 = request.form.get("address_line1")
        house.address_line2 = request.form.get("address_line2")
        house.city = request.form.get("city")
        house.state_province = request.form.get("state_province")
        house.postal_code = request.form.get("postal_code")
        house.country = request.form.get("country")

        house.location = f"{house.address_line1}, {house.city}, {house.country}"

        # ---- PRICING ----
        house.rent_amount = float(request.form.get("rent_amount") or 0)
        house.security_deposit = float(request.form.get("security_deposit") or 0)
        house.lease_term = request.form.get("lease_term")

        availability_date = request.form.get("availability_date")
        if availability_date:
            house.availability_date = datetime.strptime(availability_date, "%Y-%m-%d")

        # ---- DETAILS ----
        house.bedrooms = int(request.form.get("bedrooms") or 0)
        house.bathrooms = float(request.form.get("bathrooms") or 0)
        house.size = request.form.get("square_footage")

        # ---- FEATURES ----
        house.parking_availability = request.form.get("parking_availability")
        house.furnished_status = request.form.get("furnished_status")

        house.utilities = ",".join(request.form.getlist("utilities"))
        house.amenities = ",".join(request.form.getlist("amenities"))
        house.accessibility_features = ",".join(request.form.getlist("accessibility_features"))

        # ---- POLICIES ----
        house.pets_allowed = request.form.get("pets_allowed")
        house.pet_restrictions = request.form.get("pet_restrictions")
        house.smoking_policy = request.form.get("smoking_policy")

        # ---- IMAGES ----
        images = request.files.getlist("images")

        uploaded_urls = []  # ✅ always define it

        if images and images[0].filename != "":
            for image in images:
                try:
                    result = cloudinary.uploader.upload(
                        image,
                        folder="homehub/properties"
                    )
                    uploaded_urls.append(result.get("secure_url"))
                except Exception as e:
                    print("Upload error:", e)

            # Replace only if new images exist
            if uploaded_urls:
                house.image_urls = json.dumps(uploaded_urls)

        db.session.commit()

        flash("✅ Property updated successfully!", "success")
        return redirect(url_for("landlord.properties"))

    # -------------------
    # 🔥 FORMAT DATA FOR FORM
    # -------------------

    house.utilities = house.utilities.split(",") if house.utilities else []
    house.amenities = house.amenities.split(",") if house.amenities else []
    house.accessibility_features = house.accessibility_features.split(",") if house.accessibility_features else []

    # safe image loading
    try:
        house.image_list = json.loads(house.image_urls) if house.image_urls else []
    except:
        house.image_list = []

    house.availability_date_str = (
        house.availability_date.strftime("%Y-%m-%d")
        if house.availability_date else ""
    )

    return render_template(
        "landlord/edit_property.html",
        house=house,
        stats={}
    )


from extensions import csrf

from flask import jsonify

@landlord_bp.route('/delete_property/<int:property_id>', methods=['POST'])
@login_required
def delete_property(property_id):
    # Ensure only landlords can delete
    if current_user.role != "landlord":
        return jsonify(success=False, error="Access denied")

    # Get property
    house = House.query.get_or_404(property_id)

    # Ensure landlord owns the property
    if house.owner_id != current_user.id:
        return jsonify(success=False, error="Not allowed")

    try:
        hard = request.form.get('confirm') == 'hard'
        if hard:
            db.session.delete(house)
            db.session.commit()
            logger.info(f"Landlord {current_user.id} hard-deleted property {house.id}")
            return jsonify(success=True, message="Property permanently deleted")
        else:
            house.available = False
            db.session.commit()
            logger.info(f"Landlord {current_user.id} marked property {house.id} unavailable (soft)")
            return jsonify(success=True, message="Property marked unavailable")
    except Exception as e:
        db.session.rollback()
        logger.exception("DELETE ERROR:")
        return jsonify(success=False, error="Database error")


# ---------------- Settings ----------------
@landlord_bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if current_user.role != "landlord":
        flash("Access denied.", "danger")
        return redirect(url_for("main.index"))

    if request.method == "POST":
        try:
            # -------------------------
            # 🔐 PASSWORD CHANGE
            # -------------------------
            current_password = request.form.get("current_password")
            new_password = request.form.get("new_password")
            confirm_password = request.form.get("confirm_password")

            if new_password:  # Only if user wants to change password
                if not current_password:
                    flash("Enter current password.", "danger")
                    return redirect(url_for("landlord.settings"))

                if not current_user.check_password(current_password):
                    flash("Current password is incorrect.", "danger")
                    return redirect(url_for("landlord.settings"))

                if new_password != confirm_password:
                    flash("Passwords do not match.", "danger")
                    return redirect(url_for("landlord.settings"))

                current_user.set_password(new_password)

            # -------------------------
            # 🏠 BUSINESS INFO (OPTIONAL SAFE UPDATE)
            # -------------------------
            business_name = request.form.get("business_name")
            bio = request.form.get("bio")
            address = request.form.get("address")

            if business_name is not None:
                current_user.business_name = business_name.strip() or None

            if bio is not None:
                current_user.bio = bio.strip() or None

            if address is not None:
                current_user.address = address.strip() or None

            # -------------------------
            # 🔔 PREFERENCES
            # -------------------------
            current_user.email_notifications = bool(request.form.get("email_notifications"))
            current_user.message_alerts = bool(request.form.get("message_alerts"))

            # -------------------------
            # 🔐 2FA SETTINGS
            # -------------------------
            current_user.two_factor_enabled = bool(request.form.get("two_factor_enabled"))
            current_user.email_2fa_enabled = bool(request.form.get("email_2fa_enabled"))
            current_user.sms_2fa_enabled = bool(request.form.get("sms_2fa_enabled"))

            preferred_2fa = request.form.get("preferred_2fa_method")
            if preferred_2fa in ["email", "sms", "totp"]:
                current_user.preferred_2fa_method = preferred_2fa

            # -------------------------
            # 💾 SAVE
            # -------------------------
            db.session.commit()

            flash("Settings updated successfully!", "success")
            return redirect(url_for("landlord.settings"))

        except Exception as e:
            db.session.rollback()
            print("Settings error:", e)
            flash("Error updating settings.", "danger")
            return redirect(url_for("landlord.settings"))

    return render_template("landlord/settings.html", stats={})


# ---------------- Messages ----------------

@landlord_bp.route("/messages")
@login_required
def messages():
    if current_user.role != "landlord":
        flash("Access denied.", "danger")
        return redirect(url_for("main.index"))
    # Fetch messages where landlord is involved
    messages = Message.query.filter(
        (Message.receiver_id == current_user.id) |
        (Message.sender_id == current_user.id)
    ).order_by(Message.timestamp.desc()).all()

    return render_template("landlord/messages.html", messages=messages)

@landlord_bp.route('/delete_account', methods=['GET', 'POST'])
@login_required
def delete_account():
    if request.method == 'POST':
        from utils_delete import delete_user_and_dependents
        from flask_login import logout_user

        success, error = delete_user_and_dependents(current_user)

        if success:
            logout_user()
            flash("Your account has been deleted.", "success")
            return redirect(url_for('auth.login'))
        else:
            flash("Could not delete account: " + (error or "internal error"), "danger")
            return redirect(url_for('landlord.settings'))

    return render_template(
        'shared/delete_account.html',
        back_url=url_for('landlord.settings'),
        post_url=url_for('landlord.delete_account')
    )
    


# ---------------- Profile ----------------

@landlord_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if current_user.role != "landlord":
        flash("Access denied.", "danger")
        return redirect(url_for("main.index"))

    if request.method == "POST":
        current_user.name = request.form.get("name")
        current_user.email = request.form.get("email")
        current_user.phone_number = request.form.get("phone_number")

        # ✅ Upload to Cloudinary
        if "profile_picture" in request.files:
            picture = request.files["profile_picture"]

            if picture and picture.filename != "":
                result = cloudinary.uploader.upload(
                    picture,
                    folder="homehub/profile_pictures"
                )

                # Save Cloudinary URL in DB
                current_user.profile_picture = result.get("secure_url")

        db.session.commit()

        flash("Profile updated successfully!", "success")
        return redirect(url_for("landlord.profile"))

    return render_template("landlord/profile.html", stats={})


@landlord_bp.route("/messages/compose", methods=["GET", "POST"])
@login_required
def compose_message():
    try:
        if request.method == "POST":
            recipient_id = request.form.get("recipient_id")
            subject = request.form.get("subject")
            body = request.form.get("body")

            # Validation
            if not recipient_id or not subject or not body:
                flash("All fields are required.", "danger")
                return redirect(url_for("landlord.compose_message"))

            # Create message
            message = Message(
                sender_id=current_user.id,
                recipient_id=recipient_id,
                subject=subject,
                body=body,
                timestamp=datetime.utcnow(),
                is_read=False
            )

            db.session.add(message)
            db.session.commit()

            flash("Message sent successfully.", "success")
            return redirect(url_for("landlord.messages"))

        return render_template("compose_message.html")

    except Exception as e:
        db.session.rollback()
        flash("Error sending message. Try again.", "danger")
        print("Compose message error:", e)
        return redirect(url_for("landlord.messages"))
    
    
@landlord_bp.route('/send_message/<int:tenant_id>', methods=['GET', 'POST'])
@login_required
def send_message(tenant_id):
    tenant = User.query.get_or_404(tenant_id)

    if request.method == 'POST':
        content = request.form.get('content')

        if not content:
            flash("Message cannot be empty.", "danger")
            return redirect(url_for('landlord.send_message', tenant_id=tenant_id))

        message = Message(
            sender_id=current_user.id,
            receiver_id=tenant.id,
            content=content
        )

        db.session.add(message)
        db.session.commit()

        flash("Message sent!", "success")
        return redirect(url_for('landlord.messages'))

    return render_template('landlord/send_message.html', tenant=tenant)

@landlord_bp.route("/delete_image/<image_name>", methods=["POST"])
@login_required
def delete_image(image_name):
    import os

    image_path = os.path.join(current_app.config['UPLOAD_FOLDER'], image_name)

    if os.path.exists(image_path):
        os.remove(image_path)
        flash("Image deleted successfully", "success")
    else:
        flash("Image not found", "danger")

    return redirect(request.referrer or url_for('landlord.dashboard'))