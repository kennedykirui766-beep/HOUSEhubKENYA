import os
import logging
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from werkzeug.security import check_password_hash, generate_password_hash
from flask_login import login_required, current_user
from extensions import db, csrf
from werkzeug.utils import secure_filename
from datetime import datetime
from models.models import Message, PaymentLink, User, House, Booking, Payment, MaintenanceRequest, ServiceProvider
import cloudinary.uploader
import json

from services.email_service import send_payment_email


# Logging setup
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


def safe_datetime(val):
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    if isinstance(val, str):
        try:
            return datetime.fromisoformat(val)
        except ValueError:
            pass
    return None


def serialize_timestamp(val):
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.isoformat()
    if isinstance(val, str):
        parsed = safe_datetime(val)
        return parsed.isoformat() if parsed else val
    return None


def safe_strftime(val, format_str):
    dt = safe_datetime(val)
    if dt:
        return dt.strftime(format_str)
    return None


# Blueprint setup
landlord_bp = Blueprint("landlord", __name__, url_prefix="/landlord")

# ---------------- Landlord Dashboard ----------------
from sqlalchemy import func

@landlord_bp.route("/dashboard")
@login_required
def dashboard():
    if current_user.role != "landlord":
        flash("Access denied.", "danger")
        return redirect(url_for("main.index"))

    # 🏠 All houses
    houses = House.query.filter_by(owner_id=current_user.id).all()
    total_properties = len(houses)

    # 📋 Bookings for landlord's houses
    bookings = (
        Booking.query
        .join(House)
        .filter(House.owner_id == current_user.id)
        .all()
    )

    # 👥 Tenants (existing logic)
    tenants = (
        db.session.query(User, Booking, House)
        .join(Booking, Booking.tenant_id == User.id)
        .join(House, Booking.house_id == House.id)
        .filter(User.role == "tenant", House.owner_id == current_user.id)
        .all()
    )

    # ✅ Occupied houses (approved bookings)
    occupied_count = len([b for b in bookings if b.status == "approved"])

    occupancy_rate = (
        (occupied_count / total_properties) * 100
        if total_properties > 0 else 0
    )

    # 💰 Monthly revenue (only PAID payments this month)
    now = datetime.utcnow()

    monthly_revenue = db.session.query(func.sum(PaymentLink.amount)).filter(
        PaymentLink.landlord_id == current_user.id,
        PaymentLink.status == "paid",
        func.extract('month', PaymentLink.paid_at) == now.month,
        func.extract('year', PaymentLink.paid_at) == now.year
    ).scalar() or 0

    # ⏳ Pending booking requests
    pending_requests = len([b for b in bookings if b.status == "pending"])

    # 💳 Recent payments (last 5)
    recent_payments = (
        db.session.query(PaymentLink, User, House)
        .join(User, PaymentLink.tenant_id == User.id)
        .join(House, PaymentLink.house_id == House.id)
        .filter(PaymentLink.landlord_id == current_user.id)
        .order_by(PaymentLink.created_at.desc())
        .limit(5)
        .all()
    )

    # =========================
    # 🔔 UNREAD MESSAGES
    # =========================
    unread_messages = Message.query.filter(
        Message.receiver_id == current_user.id,
        Message.is_read == False
    ).all()

    unread_count = len(unread_messages)

    # =========================
    # GROUP BY SENDER
    # =========================
    unread_senders_dict = {}

    for msg in unread_messages:
        sender = msg.sender

        if sender.id not in unread_senders_dict:
            unread_senders_dict[sender.id] = {
                "id": sender.id,
                "name": sender.name,
                "count": 0
            }

        unread_senders_dict[sender.id]["count"] += 1

    unread_senders_list = list(unread_senders_dict.values())

    # 📊 Stats dictionary
    stats = {
        "total_properties": total_properties,
        "occupied": occupied_count,
        "occupancy_rate": round(occupancy_rate, 1),
        "monthly_revenue": monthly_revenue,
        "pending_requests": pending_requests
    }

    return render_template(
        "landlord/dashboard.html",
        houses=houses,
        tenants=tenants,
        recent_payments=recent_payments,
        stats=stats,

        # 🔔 notifications (UPDATED AS REQUESTED)
        unread_count=unread_count,
        unread_senders=unread_senders_list
    )

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

@csrf.exempt
@landlord_bp.route("/api/generate-payment-link", methods=["POST"])
@login_required
def api_generate_payment_link():
    try:
        data = request.get_json()
        booking_id = data.get("booking_id")

        if not booking_id:
            return jsonify({
                "success": False,
                "message": "Missing booking ID"
            }), 400

        booking = Booking.query.get_or_404(booking_id)

        # 🚫 Authorization check
        if booking.house.owner_id != current_user.id:
            return jsonify({
                "success": False,
                "message": "Unauthorized access"
            }), 403

        import uuid
        from datetime import datetime, timedelta  # ✅ ADD THIS

        token = str(uuid.uuid4())

        link = PaymentLink(
            token=token,
            landlord_id=current_user.id,
            booking_id=booking.id,
            tenant_id=booking.tenant_id,
            house_id=booking.house_id,
            amount=booking.house.security_deposit,
            status="pending",
            expires_at=datetime.utcnow() + timedelta(minutes=10)  # ✅ 10 MIN EXPIRY
        )

        db.session.add(link)
        db.session.commit()

        payment_url = url_for(
            "payments.pay",
            token=token,
            _external=True
        )

        # ✅ SEND EMAIL
        try:
            send_payment_email(
                to_email=booking.tenant.email,
                tenant_name=booking.tenant.name,
                payment_url=payment_url,
                amount=link.amount
            )
        except Exception as e:
            import traceback
            print("❌ EMAIL FAILED:")
            traceback.print_exc()

            # ❗ Return failure instead of pretending success
            return jsonify({
                "success": False,
                "message": f"Email sending failed: {str(e)}"
            }), 500

        return jsonify({
            "success": True,
            "payment_url": payment_url
        })

    except Exception as e:
        import traceback
        print("❌ API ERROR:")
        traceback.print_exc()

        return jsonify({
            "success": False,
            "message": f"Server error: {str(e)}"
        }), 500

# ---------------- Payments ----------------
from datetime import datetime

@landlord_bp.route("/payments")
@login_required
def payments():
    if current_user.role != "landlord":
        flash("Access denied.", "danger")
        return redirect(url_for("main.index"))

    payments = (
        db.session.query(PaymentLink, User, House)
        .join(User, PaymentLink.tenant_id == User.id)
        .join(House, PaymentLink.house_id == House.id)
        .filter(PaymentLink.landlord_id == current_user.id)
        .order_by(PaymentLink.created_at.desc())
        .all()
    )

    # ✅ Calculate stats in Python
    total_collected = sum(
        payment.amount
        for payment, tenant, house in payments
        if payment.status == "paid"
    )

    pending_count = sum(
        1 for payment, tenant, house in payments
        if payment.status == "pending"
    )

    return render_template(
        "landlord/payments.html",
        payments=payments,
        stats={
            "total_collected": total_collected,
            "pending_count": pending_count
        }
    )


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
        .join(House, MaintenanceRequest.house_id == House.id)
        .filter(House.owner_id == current_user.id)
        .order_by(MaintenanceRequest.date_submitted.desc())
        .all()
    )

    stats = {
        "total": len(requests),
        "pending": len([r for r, u, h in requests if r.status == "pending"]),
        "in_progress": len([r for r, u, h in requests if r.status == "in_progress"]),
        "completed": len([r for r, u, h in requests if r.status == "completed"]),
    }

    return render_template(
        "landlord/maintenance.html",
        requests=requests,
        stats=stats
    )


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
from datetime import datetime
from sqlalchemy import func

@landlord_bp.route("/reports")
@login_required
def reports():
    if current_user.role != "landlord":
        flash("Access denied.", "danger")
        return redirect(url_for("main.index"))

    now = datetime.utcnow()

    # 💰 Total revenue
    total_revenue = db.session.query(func.sum(PaymentLink.amount)).filter(
        PaymentLink.landlord_id == current_user.id,
        PaymentLink.status == "paid"
    ).scalar() or 0

    # 💰 Monthly revenue
    monthly_revenue = db.session.query(func.sum(PaymentLink.amount)).filter(
        PaymentLink.landlord_id == current_user.id,
        PaymentLink.status == "paid",
        func.extract('month', PaymentLink.paid_at) == now.month,
        func.extract('year', PaymentLink.paid_at) == now.year
    ).scalar() or 0

    # 🏠 Properties
    total_properties = House.query.filter_by(owner_id=current_user.id).count()

    # 📋 Bookings
    bookings = (
        Booking.query
        .join(House)
        .filter(House.owner_id == current_user.id)
        .all()
    )

    occupied = len([b for b in bookings if b.status == "approved"])
    pending = len([b for b in bookings if b.status == "pending"])

    occupancy_rate = (occupied / total_properties * 100) if total_properties else 0

    # 👥 Tenants
    total_tenants = len(set([b.tenant_id for b in bookings]))

    # 💳 Payments breakdown
    paid_count = PaymentLink.query.filter_by(
        landlord_id=current_user.id, status="paid"
    ).count()

    expired_count = PaymentLink.query.filter_by(
        landlord_id=current_user.id, status="expired"
    ).count()

    stats = {
        "total_revenue": total_revenue,
        "monthly_revenue": monthly_revenue,
        "total_properties": total_properties,
        "occupied": occupied,
        "occupancy_rate": round(occupancy_rate, 1),
        "pending_bookings": pending,
        "total_tenants": total_tenants,
        "paid_payments": paid_count,
        "expired_payments": expired_count
    }

    return render_template("landlord/reports.html", stats=stats)


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
        safe_strftime(house.availability_date, "%Y-%m-%d")
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

    # ✅ NEW: get selected tenant
    selected_user_id = request.args.get("tenant_id")

    # =========================
    # ✅ NEW: MARK AS READ
    # =========================
    if selected_user_id:
        try:
            Message.query.filter(
                Message.sender_id == int(selected_user_id),
                Message.receiver_id == current_user.id,
                Message.is_read == False
            ).update({"is_read": True})

            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print("Read update error:", e)

    msgs_query = Message.query.filter(
        (Message.receiver_id == current_user.id) |
        (Message.sender_id == current_user.id)
    ).order_by(Message.timestamp.asc()).all()

    messages_data = []
    for m in msgs_query:
        if m.sender_id == current_user.id:
            other_id = m.receiver_id
            other_name = m.receiver.name
            other_avatar = getattr(m.receiver, 'profile_picture', None)
        else:
            other_id = m.sender_id
            other_name = m.sender.name
            other_avatar = getattr(m.sender, 'profile_picture', None)

        messages_data.append({
            "id": m.id,
            "sender_id": m.sender_id,
            "receiver_id": m.receiver_id,
            "content": m.content,
            "timestamp": serialize_timestamp(m.timestamp),
            "other_user": {
                "id": other_id,
                "name": other_name,
                "avatar": other_avatar
            }
        })

    user_data = {
        "id": current_user.id,
        "name": current_user.name,
        "role": current_user.role
    }

    return render_template(
        'landlord/messages.html',
        messages=messages_data,
        user=user_data,
        selected_user_id=int(selected_user_id) if selected_user_id else None  # ✅ NEW
    )

@csrf.exempt
@landlord_bp.route("/messages/mark_all_read", methods=["POST"])
@login_required
def mark_all_messages_read():
    if current_user.role != "landlord":
        return {"success": False, "error": "Unauthorized"}, 403

    try:
        unread_messages = Message.query.filter(
            Message.receiver_id == current_user.id,
            Message.is_read == False
        ).all()

        for msg in unread_messages:
            msg.is_read = True
            msg.read_at = datetime.utcnow()

        db.session.commit()

        return {"success": True, "updated": len(unread_messages)}

    except Exception as e:
        db.session.rollback()
        print("Mark all read error:", e)
        return {"success": False}, 500
    
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
    

# --- GET MESSAGES FOR SPECIFIC CHAT ---
@landlord_bp.route('/get_messages/<int:other_user_id>')
@login_required
def get_messages(other_user_id):
    """
    Returns JSON list of messages between current user and other_user_id
    """
    messages = Message.query.filter(
        ((Message.sender_id == current_user.id) & (Message.receiver_id == other_user_id)) |
        ((Message.sender_id == other_user_id) & (Message.receiver_id == current_user.id))
    ).order_by(Message.timestamp.asc()).all()
    
    message_list = []
    for msg in messages:
        message_list.append({
            'id': msg.id,
            'sender_id': msg.sender_id,
            'receiver_id': msg.receiver_id,
            'content': msg.content,
            'timestamp': msg.timestamp.isoformat() if msg.timestamp else None,
            'is_read': msg.is_read
        })
        
    return jsonify(message_list)


# --- SEND MESSAGE ---
@csrf.exempt
@landlord_bp.route('/send_message', methods=['POST'])
@login_required
def send_message():
    from datetime import datetime

    data = request.get_json()

    receiver_id = data.get("receiver_id")
    content = data.get("content")

    if not receiver_id or not content:
        return {"success": False, "error": "Missing data"}, 400

    try:
        message = Message(
            sender_id=current_user.id,
            receiver_id=receiver_id,
            content=content,
            timestamp=datetime.utcnow(),
            is_read=False   # 👈 important
        )

        db.session.add(message)
        db.session.commit()

        return {
            "success": True,
            "message": {
                "id": message.id,
                "sender_id": message.sender_id,
                "receiver_id": message.receiver_id,
                "content": message.content,
                "timestamp": message.timestamp.isoformat(),  # 👈 critical
                "is_read": message.is_read
            }
        }

    except Exception as e:
        db.session.rollback()
        print("Error:", e)
        return {"success": False, "error": str(e)}, 500

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

@landlord_bp.route("/bookings")
@login_required
def bookings():
    if current_user.role != "landlord":
        flash("Access denied.", "danger")
        return redirect(url_for("main.index"))

    # 📋 Get all bookings for houses owned by landlord
    bookings = (
        db.session.query(Booking, User, House)
        .join(User, Booking.tenant_id == User.id)
        .join(House, Booking.house_id == House.id)
        .filter(House.owner_id == current_user.id)
        .order_by(Booking.created_at.desc())
        .all()
    )

    # 📊 Stats (optional but useful)
    stats = {
        "total": len(bookings),
        "pending": len([b for b, u, h in bookings if b.status == "pending"]),
        "approved": len([b for b, u, h in bookings if b.status == "approved"]),
        "rejected": len([b for b, u, h in bookings if b.status == "rejected"]),
    }

    return render_template(
        "landlord/bookings.html",
        bookings=bookings,
        stats=stats
    )