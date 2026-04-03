from flask import (
    Blueprint, render_template, redirect, request,
    url_for, flash, current_app as app, session
)
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import login_user, logout_user, login_required, current_user
from models.models import User, TwoFactorCode, TwoFactorVerification
from extensions import db
from utils_2fa import (
    create_verification_code,
    verify_code,
    get_or_create_2fa_verification,
    generate_backup_codes,
    has_valid_2fa_method,
    get_enabled_2fa_methods
)
from utils_email_2fa import send_2fa_email, verify_email_format
from sqlalchemy.exc import IntegrityError
import re
import logging
import pyotp
from werkzeug.utils import secure_filename
import os
from flask import current_app
import cloudinary.uploader

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

            # Handle legacy 2FA (TOTP)
            if user.two_factor_enabled:
                if not two_factor_code:
                    flash("2FA code required.", "warning")
                    return render_template("login.html", requires_2fa=True)
                if not verify_2fa_code(user, two_factor_code):
                    flash("Invalid 2FA code.", "danger")
                    return render_template("login.html")
            
            # Check if user has new-style 2FA enabled (email/SMS)
            elif has_valid_2fa_method(user):
                # Send verification code
                preferred_method = user.preferred_2fa_method or 'email'
                code_obj = create_verification_code(user, method=preferred_method)
                
                if preferred_method == 'email':
                    if send_2fa_email(user.email, user.name, code_obj.code):
                        session['pending_2fa_user_id'] = user.id
                        session['2fa_method'] = preferred_method
                        return redirect(url_for('auth.verify_2fa_login'))
                    else:
                        flash("Failed to send 2FA email. Try again.", "danger")
                        return render_template("login.html")
                # SMS will be added in Phase 2
            
            # No 2FA enabled

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
            db.session.rollback()
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

            # Phone validation
            if not re.match(r"^\d{9}$", phone_number):
                flash("Phone number must be 9 digits after +254.", "danger")
                return redirect(url_for("auth.signup"))

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

            # 🔥 Upload to Cloudinary
            profile_picture_url = None
            if profile_picture and profile_picture.filename:
                upload_result = cloudinary.uploader.upload(
                    profile_picture,
                    folder="homehub/profile_pictures",
                    resource_type="image"
                )
                profile_picture_url = upload_result.get("secure_url")

            # Create user
            user = User(
                name=full_name,
                email=email,
                phone_number=full_phone,  # ✅ FIXED
                role=role,
                mpesa_details=mpesa_details if role in ["landlord", "service"] else None,
                profile_picture=profile_picture_url,  # ✅ URL instead of local path
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


# ================ EMAIL 2FA SETUP ================
@auth_bp.route('/setup-email-2fa', methods=['GET', 'POST'])
@login_required
def setup_email_2fa():
    """Start email 2FA setup - send initial verification code"""
    if request.method == 'POST':
        # Generate OTP and send to user's email
        code_obj = create_verification_code(current_user, method='email')
        
        if send_2fa_email(current_user.email, current_user.name, code_obj.code):
            session['email_2fa_pending'] = True
            flash("Verification code sent to your email.", "info")
            return redirect(url_for('auth.verify_email_2fa'))
        else:
            flash("Failed to send email. Please try again.", "danger")
    
    # Check if email 2FA already enabled
    verification = current_user.two_factor_verification
    email_enabled = verification.email_enabled if verification else False
    
    return render_template('setup_email_2fa.html', email_enabled=email_enabled)


@auth_bp.route('/verify-email-2fa', methods=['GET', 'POST'])
@login_required
def verify_email_2fa():
    """Verify email code and enable email 2FA"""
    if not session.get('email_2fa_pending'):
        flash("Please start the setup process first.", "warning")
        return redirect(url_for('auth.setup_email_2fa'))
    
    if request.method == 'POST':
        code = request.form.get('code', '').strip()
        
        if not code:
            flash("Please enter the verification code.", "danger")
            return render_template('verify_email_2fa.html')
        
        # Verify the code
        if verify_code(current_user, code, method='email'):
            # Enable email 2FA
            verification = get_or_create_2fa_verification(current_user)
            verification.email_enabled = True
            
            # Generate backup codes if first time enabling any method
            if not verification.backup_codes:
                verification.backup_codes = generate_backup_codes(10)
            
            # Set as preferred method if no other method enabled
            if current_user.preferred_2fa_method is None:
                current_user.preferred_2fa_method = 'email'
            
            db.session.commit()
            
            session.pop('email_2fa_pending', None)
            flash("Email 2FA enabled successfully!", "success")
            return redirect(url_for('auth.show_backup_codes'))
        else:
            flash("Invalid or expired code. Please try again.", "danger")
            return render_template('verify_email_2fa.html')
    
    return render_template('verify_email_2fa.html')


@auth_bp.route('/backup-codes')
@login_required
def show_backup_codes():
    """Display backup codes for account recovery"""
    verification = current_user.two_factor_verification
    
    if not verification or not verification.backup_codes:
        flash("No backup codes found. Enable 2FA first.", "warning")
        return redirect(url_for('auth.setup_email_2fa'))
    
    codes = verification.get_backup_codes()
    return render_template('backup_codes.html', codes=codes, user=current_user)


@auth_bp.route('/verify-2fa-login', methods=['GET', 'POST'])
def verify_2fa_login():
    """Verify 2FA code during login"""
    user_id = session.get('pending_2fa_user_id')
    method = session.get('2fa_method', 'email')
    
    if not user_id:
        flash("Please log in first.", "warning")
        return redirect(url_for('auth.login'))
    
    user = User.query.get(user_id)
    if not user:
        flash("User not found.", "danger")
        return redirect(url_for('auth.login'))
    
    if request.method == 'POST':
        code = request.form.get('code', '').strip()
        
        if not code:
            flash("Please enter the verification code.", "danger")
            return render_template('verify_2fa_login.html', method=method, masked_email=user.email[:3] + '***' + user.email[-10:])
        
        # Check if backup code (starts with letter, 8 chars)
        if len(code) == 8 and code[0].isalpha():
            verification = user.two_factor_verification
            if verification and verification.use_backup_code(code):
                db.session.commit()
                session.pop('pending_2fa_user_id')
                session.pop('2fa_method')
                login_user(user)
                flash("Logged in with backup code. Please generate new backup codes.", "warning")
                logger.info(f"User {user.id} logged in with backup code")
                return redirect(url_for('auth.show_backup_codes'))
            else:
                flash("Invalid backup code.", "danger")
        
        # Regular OTP verification
        elif verify_code(user, code, method=method):
            session.pop('pending_2fa_user_id')
            session.pop('2fa_method')
            login_user(user)
            flash("Login successful.", "success")
            logger.info(f"User {user.id} logged in with {method} 2FA")
            
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
                return redirect(url_for("main.index"))
        else:
            flash("Invalid or expired code. Please request a new one.", "danger")
            return render_template('verify_2fa_login.html', method=method, masked_email=user.email[:3] + '***' + user.email[-10:])
    
    masked_email = user.email[:3] + '***' + user.email[-10:]
    return render_template('verify_2fa_login.html', method=method, masked_email=masked_email)


@auth_bp.route('/disable-email-2fa', methods=['POST'])
@login_required
def disable_email_2fa():
    """Disable email 2FA"""
    verification = current_user.two_factor_verification
    
    if not verification or not verification.email_enabled:
        flash("Email 2FA is not enabled.", "warning")
        return redirect(url_for('auth.security_settings'))
    
    verification.email_enabled = False
    db.session.commit()
    
    flash("Email 2FA disabled.", "success")
    logger.info(f"User {current_user.id} disabled email 2FA")
    return redirect(url_for('auth.security_settings'))


@auth_bp.route('/regenerate-backup-codes', methods=['POST'])
@login_required
def regenerate_backup_codes():
    """Generate new backup codes"""
    verification = get_or_create_2fa_verification(current_user)
    verification.backup_codes = generate_backup_codes(10)
    db.session.commit()
    
    flash("New backup codes generated.", "success")
    logger.info(f"User {current_user.id} regenerated backup codes")
    return redirect(url_for('auth.show_backup_codes'))


@auth_bp.route('/security-settings')
@login_required
def security_settings():
    """View and manage 2FA settings"""
    verification = current_user.two_factor_verification
    
    enabled_methods = get_enabled_2fa_methods(current_user) if verification else []
    
    return render_template('security_settings.html', 
                          verification=verification,
                          enabled_methods=enabled_methods)


# ================ VERIFY 2FA (Legacy TOTP) ================
def verify_2fa_code(user, code):
    if not user.two_factor_secret:
        return False
    totp = pyotp.TOTP(user.two_factor_secret)
    return totp.verify(code)


@auth_bp.route('/social-login/<provider>')
def social_login(provider):
    return f"Social login with {provider} coming soon"