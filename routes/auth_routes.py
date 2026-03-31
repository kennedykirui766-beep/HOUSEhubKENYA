from flask import (
    Blueprint, render_template, redirect, request,
    url_for, flash, current_app as app
)
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import login_user, logout_user, login_required, current_user
from models.models import User
from extensions import db
from sqlalchemy.exc import IntegrityError
import re
import logging
import pyotp
from werkzeug.utils import secure_filename
import os

# ------------------- LOGGING -------------------
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__)


# ------------------- LOGIN -------------------
@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        try:
            identifier = request.form.get("identifier")  # email or phone
            password = request.form.get("password")
            two_factor_code = request.form.get("two_factor_code")
            remember_me = request.form.get("remember_me") == "on"

            if not identifier or not password:
                flash("Email/phone and password are required.", "danger")
                return render_template("login.html")

            # Query user by email or phone
            user = User.query.filter(
                (User.email == identifier) | (User.phone_number == identifier)
            ).first()

            if not user:
                flash("Email or phone number not recognized.", "danger")
                return render_template("login.html")

            if not user.check_password(password):
                flash("Incorrect password.", "danger")
                return render_template("login.html")

            # Handle 2FA if enabled
            if user.two_factor_enabled:
                if not two_factor_code:
                    flash("2FA code required.", "warning")
                    return render_template("login.html", requires_2fa=True)
                if not verify_2fa_code(user, two_factor_code):
                    flash("Invalid 2FA code.", "danger")
                    return render_template("login.html")

            login_user(user, remember=remember_me)
            flash("Login successful.", "success")
            logger.debug(f"User {identifier} logged in.")

            # Redirect based on role
            if user.role == "tenant":
                return redirect(url_for("tenant.dashboard"))
            elif user.role == "landlord":
                return redirect(url_for("landlord.dashboard"))
            elif user.role == "service":
                return redirect(url_for("service_provider.dashboard"))
            elif user.role == "admin":
                return redirect(url_for("admin.dashboard"))
            else:
                return redirect(url_for("portal"))

        except Exception as e:
            logger.error(f"Login error: {str(e)}", exc_info=True)
            flash("An error occurred during login. Try again.", "danger")
            return render_template("login.html")

    return render_template("login.html")


# ------------------- SIGNUP -------------------
@auth_bp.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        try:
            full_name = request.form.get("full_name")
            email = request.form.get("email")
            phone_number = request.form.get("phone_number")
            password = request.form.get("password")
            confirm_password = request.form.get("confirm_password")
            role = request.form.get("role")
            mpesa_details = request.form.get("mpesa_details")
            profile_picture = request.files.get("profile_picture")
            language = request.form.get("language", "en")
            terms = request.form.get("terms")

            logger.debug(
                f"Signup request: {full_name}, {email}, {phone_number}, role={role}"
            )

            # Required fields
            if not all([full_name, email, phone_number, password, confirm_password, role, terms]):
                flash("Fill in all required fields and accept terms.", "danger")
                return redirect(url_for("auth.signup"))

            # Role validation
            if role not in ["tenant", "landlord", "service", "admin"]:
                flash("Invalid role.", "danger")
                return redirect(url_for("auth.signup"))

            # ✅ Phone validation (Kenya format: 9 digits after +254)
            if not re.match(r"^\d{9}$", phone_number):
                flash("Phone number must be 9 digits after +254.", "danger")
                return redirect(url_for("auth.signup"))

            # Optional: Add prefix before saving to DB
            full_phone = f"+254{phone_number}"


            # Password validation
            if not re.match(
                r"^(?=.*[a-zA-Z])(?=.*\d)(?=.*[!@#$%^&*()_+\-=\\[\]{};':\"|,.<>/?]).{8,}$",
                password,
            ):
                flash("Password too weak (min 8 chars, digit, special char).", "danger")
                return redirect(url_for("auth.signup"))

            if password != confirm_password:
                flash("Passwords do not match.", "danger")
                return redirect(url_for("auth.signup"))

            # Profile picture handling
            profile_picture_path = None
            if profile_picture and profile_picture.filename:
                filename = secure_filename(profile_picture.filename)
                upload_folder = app.config.get("UPLOAD_FOLDER", "static/images")
                os.makedirs(upload_folder, exist_ok=True)
                profile_picture_path = os.path.join(upload_folder, filename)
                profile_picture.save(profile_picture_path)

            # Create user
            user = User(
                name=full_name,
                email=email,
                phone_number=phone_number,
                role=role,
                mpesa_details=mpesa_details if role in ["landlord", "service"] else None,
                profile_picture=profile_picture_path,
                language=language,
            )
            user.set_password(password)

            db.session.add(user)
            db.session.commit()
            flash("Account created. Please login.", "success")
            logger.debug(f"User {email} created.")
            return redirect(url_for("auth.login"))

        except IntegrityError:
            db.session.rollback()
            flash("Email or phone already registered.", "danger")
            return redirect(url_for("auth.signup"))
        except Exception as e:
            db.session.rollback()
            logger.error(f"Signup error: {str(e)}", exc_info=True)
            flash("Error creating account. Try again.", "danger")
            return redirect(url_for("auth.signup"))

    return render_template("signup.html")


# ------------------- TERMS -------------------
@auth_bp.route("/terms")
def terms():
    return render_template("terms.html")


# ------------------- FORGOT PASSWORD -------------------
@auth_bp.route("/forgot_password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        identifier = request.form.get("identifier")
        if not identifier:
            flash("Provide email or phone number.", "danger")
            return render_template("forgot_password.html")

        user = User.query.filter(
            (User.email == identifier) | (User.phone_number == identifier)
        ).first()

        if not user:
            flash("Email/phone not found.", "danger")
            return render_template("forgot_password.html")

        # TODO: Send real reset link (email/SMS)
        flash("Password reset link sent.", "success")
        logger.debug(f"Password reset requested for {identifier}")
        return redirect(url_for("auth.login"))

    return render_template("forgot_password.html")


# ------------------- SUPPORT -------------------
@auth_bp.route("/support", methods=["GET", "POST"])
def support():
    if request.method == "POST":
        try:
            name = request.form.get("name")
            email = request.form.get("email")
            message = request.form.get("message")

            if not all([name, email, message]):
                flash("Fill in all required fields.", "danger")
                return redirect(url_for("auth.support"))

            # TODO: Save to DB or email admin
            flash("Support request submitted. We'll contact you.", "success")
            logger.debug(f"Support request from {email}")
            return redirect(url_for("auth.support"))

        except Exception as e:
            logger.error(f"Support form error: {str(e)}", exc_info=True)
            flash("Error submitting support request.", "danger")
            return redirect(url_for("auth.support"))

    return render_template("support.html")


# ------------------- LOGOUT -------------------
@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Logged out successfully.", "info")
    return redirect(url_for("auth.login"))


# ------------------- PROFILE -------------------
@auth_bp.route("/profile")
@login_required
def profile():
    return render_template("profile.html", user=current_user)

# ------------------- UPDATE PROFILE -------------------
@auth_bp.route("/update_profile", methods=["POST"])
@login_required
def update_profile():
    try:
        current_user.name = request.form.get("name")
        current_user.email = request.form.get("email")

        phone_number = request.form.get("phone_number")
        if phone_number:
            if not re.match(r"^\+254\d{9}$", phone_number):
                flash("Phone number must be in +254XXXXXXXXX format.", "danger")
                return redirect(url_for("auth.profile"))
            current_user.phone_number = phone_number

        if "profile_picture" in request.files:
            picture = request.files["profile_picture"]
            if picture and picture.filename:
                filename = secure_filename(picture.filename)
                upload_folder = app.config.get("UPLOAD_FOLDER", "static/images")
                os.makedirs(upload_folder, exist_ok=True)
                path = os.path.join(upload_folder, filename)
                picture.save(path)
                current_user.profile_picture = path

        db.session.commit()
        flash("Profile updated successfully.", "success")
        logger.debug(f"Profile updated for {current_user.email}")
    except IntegrityError:
        db.session.rollback()
        flash("Email or phone already taken.", "danger")
    except Exception as e:
        db.session.rollback()
        logger.error(f"Profile update error: {str(e)}", exc_info=True)
        flash("Error updating profile.", "danger")

    return redirect(url_for("auth.profile"))


# ------------------- VERIFY 2FA -------------------
def verify_2fa_code(user, code):
    if not user.two_factor_secret:
        return False
    totp = pyotp.TOTP(user.two_factor_secret)
    return totp.verify(code)
