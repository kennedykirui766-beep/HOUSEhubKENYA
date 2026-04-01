import os
import logging
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from datetime import datetime
from extensions import db, csrf
from models.models import User, House, Booking, Payment, MaintenanceRequest, ServiceProvider
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

    tenants = (
        db.session.query(User, Booking, House)
        .join(Booking, Booking.tenant_id == User.id)
        .join(House, Booking.house_id == House.id)
        .filter(User.role == "tenant", House.owner_id == current_user.id)
        .all()
    )
    return render_template("landlord/tenants.html", tenants=tenants, stats={})


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

    house = House.query.filter_by(id=property_id, owner_id=current_user.id).first_or_404()

    if request.method == "POST":
        house.title = request.form.get("title")
        house.description = request.form.get("description")
        house.location = request.form.get("location")
        house.rent_amount = request.form.get("rent_amount")

        db.session.commit()
        flash("Property updated successfully!", "success")
        return redirect(url_for("landlord.properties"))

    return render_template("landlord/edit_property.html", house=house, stats={})


@landlord_bp.route('/delete-property/<int:property_id>', methods=['POST'])
@login_required
def delete_property(property_id):
    # Ensure only landlords can delete
    if current_user.role != "landlord":
        flash("Access denied.", "danger")
        return redirect(url_for("main.index"))

    # Get property
    property = House.query.get_or_404(property_id)

    # Ensure landlord owns the property
    if property.owner_id != current_user.id:
        flash("You are not allowed to delete this property.", "danger")
        return redirect(url_for("landlord.properties"))

    try:
        db.session.delete(property)
        db.session.commit()
        flash("Property deleted successfully.", "success")
    except Exception as e:
        db.session.rollback()
        flash("Error deleting property.", "danger")

    return redirect(url_for("landlord.properties"))


# ---------------- Settings ----------------
@landlord_bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if current_user.role != "landlord":
        flash("Access denied.", "danger")
        return redirect(url_for("main.index"))

    if request.method == "POST":
        # Later: save landlord preferences here (e.g., language, notifications)
        flash("Settings updated successfully!", "success")
        return redirect(url_for("landlord.settings"))

    return render_template("landlord/settings.html", stats={})


# ---------------- Messages ----------------
@landlord_bp.route("/messages")
@login_required
def messages():
    if current_user.role != "landlord":
        flash("Access denied.", "danger")
        return redirect(url_for("main.index"))

    # TODO: Load landlord messages
    return render_template("landlord/messages.html", stats={})


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

        if "profile_picture" in request.files:
            picture = request.files["profile_picture"]
            if picture:
                filename = secure_filename(picture.filename)
                filepath = os.path.join(current_app.config["UPLOAD_FOLDER"], filename)
                picture.save(filepath)
                current_user.profile_picture = filename

        db.session.commit()
        flash("Profile updated successfully!", "success")
        return redirect(url_for("landlord.profile"))

    return render_template("landlord/profile.html", stats={})
