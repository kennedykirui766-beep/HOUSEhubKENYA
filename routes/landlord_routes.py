import os
import logging
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from datetime import datetime
from extensions import db, csrf
from models.models import User, House, Booking, Payment, MaintenanceRequest, ServiceProvider

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
@landlord_bp.route("/properties")
@login_required
def properties():
    if current_user.role != "landlord":
        flash("Access denied.", "danger")
        return redirect(url_for("main.index"))

    properties = House.query.filter_by(owner_id=current_user.id).all()
    return render_template("landlord/properties.html", properties=properties, stats={})


# ---------------- Add Property ----------------
@landlord_bp.route("/properties/add", methods=["GET", "POST"])
@login_required
def add_property():
    if current_user.role != "landlord":
        flash("Access denied.", "danger")
        return redirect(url_for("main.index"))

    if request.method == "POST":
        title = request.form.get("title")
        description = request.form.get("description")
        location = request.form.get("location")
        rent_amount = request.form.get("rent_amount")

        house = House(
            title=title,
            description=description,
            location=location,
            rent_amount=rent_amount,
            owner_id=current_user.id,
        )
        db.session.add(house)
        db.session.commit()

        flash("Property added successfully!", "success")
        return redirect(url_for("landlord.properties"))

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
