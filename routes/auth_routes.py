from flask import (
    Blueprint, render_template, redirect, request,
    url_for, flash, current_app as app, session
)
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import login_user, logout_user, login_required, current_user
from models.models import User, TwoFactorCode, TwoFactorVerification, SystemSetting
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
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from utils_security import (
    consume_rate_limit,
    is_approved_admin,
    mark_admin_totp_verified,
    clear_admin_totp_verification,
    get_allowed_admin_email,
    has_admin_totp_verified,
)
from sqlalchemy.exc import IntegrityError
import re
import logging
import pyotp
import time
import base64
from io import BytesIO
from werkzeug.utils import secure_filename
import os
from flask import current_app
import cloudinary.uploader
import qrcode
from extensions import db, csrf
from services.notification import enqueue_password_reset_email

# ------------------- LOGGING -------------------
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__)

PASSWORD_RESET_SALT = "homehub-password-reset"


def _get_password_reset_serializer():
    secret_key = current_app.config.get('SECRET_KEY') or current_app.secret_key
    if not secret_key:
        raise RuntimeError('SECRET_KEY is required for password reset tokens.')
    return URLSafeTimedSerializer(secret_key)


def _build_password_reset_token(user):
    serializer = _get_password_reset_serializer()
    return serializer.dumps({'user_id': user.id, 'email': user.email}, salt=PASSWORD_RESET_SALT)


def _verify_password_reset_token(token, max_age_seconds=3600):
    serializer = _get_password_reset_serializer()
    data = serializer.loads(token, salt=PASSWORD_RESET_SALT, max_age=max_age_seconds)
    user_id = data.get('user_id')
    email = (data.get('email') or '').strip().lower()
    if not user_id or not email:
        return None
    user = User.query.get(user_id)
    if not user or (user.email or '').strip().lower() != email:
        return None
    return user


def _queue_password_reset(user):
    reset_token = _build_password_reset_token(user)
    reset_url = url_for('auth.reset_password', token=reset_token, _external=True)
    enqueue_password_reset_email(user.email, user.name, reset_url, expires_minutes=60)
    return reset_url


def _purge_reserved_admin_email_accounts():
    allowed_admin_email = (get_allowed_admin_email() or '').strip().lower()
    if not allowed_admin_email:
        return

    reserved_accounts = User.query.filter(User.email == allowed_admin_email).all()
    removed_any = False
    for account in reserved_accounts:
        if account.role != 'admin':
            db.session.delete(account)
            removed_any = True

    if removed_any:
        db.session.commit()
        logger.info("Removed non-admin account(s) using the reserved admin email")


# ------------------- LOGIN -------------------
@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    admin_entry_required = bool(session.get('admin_entry_granted'))

    if request.method == "POST":
        try:
            _purge_reserved_admin_email_accounts()

            identifier = request.form.get("identifier")  # email or phone
            password = request.form.get("password")
            two_factor_code = request.form.get("two_factor_code")
            remember_me = request.form.get("remember_me") == "on"

            rate_limit_key = f"login:{(identifier or request.remote_addr or 'unknown').strip().lower()}"
            allowed, retry_after = consume_rate_limit(rate_limit_key, 5, 60)
            if not allowed:
                flash(f"Too many login attempts. Please wait {retry_after}s and try again.", "warning")
                return render_template("login.html")

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

            if user.role == "admin" and not is_approved_admin(user):
                flash("This admin account is not approved for platform administration.", "danger")
                return render_template("login.html")

            if user.role == "admin":
                # Admin users must start from the private semantic entry link.
                if not session.get('admin_entry_granted'):
                    flash("Admin access requires the private admin access link.", "warning")
                    return redirect(url_for('auth.semantic_admin_entry'))

                allowed_admin_email = (get_allowed_admin_email() or '').strip().lower()
                if not allowed_admin_email or (user.email or '').strip().lower() != allowed_admin_email:
                    flash("Use the approved admin email for this environment.", "danger")
                    return render_template("login.html")

            # Always verify the user's account email before granting access.
            code_obj = create_verification_code(user, method='email')
            if send_2fa_email(user.email, user.name, code_obj.code, method='login'):
                session['pending_2fa_user_id'] = user.id
                session['2fa_method'] = 'email'
                session['remember_me'] = remember_me
                session['otp_resend_allowed_at'] = int(time.time()) + 30
                flash("We sent a login code to your account email. Enter it to continue.", "info")
                return redirect(url_for('auth.verify_2fa_login'))

            flash("Failed to send the login code. Please try again.", "danger")
            return render_template("login.html")

            # Redirect based on role
            if user.role == "tenant":
                return redirect(url_for("tenant.dashboard"))
            elif user.role == "landlord":
                return redirect(url_for("landlord.dashboard"))
            elif user.role == "service":
                return redirect(url_for("main.index"))
            elif user.role == "admin":
                return redirect(url_for("admin.dashboard"))
            else:
                return redirect(url_for("portal"))

        except Exception as e:
            db.session.rollback()
            logger.error(f"Login error: {str(e)}", exc_info=True)
            flash("An error occurred during login. Try again.", "danger")
            return render_template("login.html")

    return render_template("login.html", admin_entry_required=admin_entry_required)

@auth_bp.route('/semantic/admin')
def semantic_admin_entry():
    """Private admin entrypoint page."""
    return render_template('semantic_admin_entry.html')

@auth_bp.route('/semantic/admin/continue', methods=['POST'])
def semantic_admin_continue():
    """Confirm the private admin entry and move to login."""

    # Optional: set admin password if provided
    allowed_admin_email = (get_allowed_admin_email() or '').strip().lower()
    admin_password = request.form.get('admin_password')

    if allowed_admin_email and admin_password:
        try:
            user = User.query.filter_by(email=allowed_admin_email).first()
            if user:
                user.role = 'admin'
                user.set_password(admin_password)
            else:
                user = User(name='Admin', email=allowed_admin_email, role='admin')
                user.set_password(admin_password)

            db.session.add(user)
            db.session.commit()
            flash('Admin password set. Continue to login.', 'success')

        except Exception:
            db.session.rollback()
            logger.exception('Failed to set admin password')
            flash('Failed to set admin password. Contact support.', 'danger')

    session['admin_entry_granted'] = True
    session['admin_entry_granted_at'] = int(time.time())

    flash("Admin entry confirmed. Continue with the approved email and password.", "info")
    return redirect(url_for('auth.login'))


# ------------------- SIGNUP -------------------
@auth_bp.route("/signup", methods=["GET", "POST"])
def signup():
    if SystemSetting.get('feature_signup_enabled', '1') != '1':
        flash('Signups are temporarily disabled by the platform administrator.', 'warning')
        return redirect(url_for('auth.login'))

    if request.method == "POST":
        try:
            _purge_reserved_admin_email_accounts()

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
            allowed_admin_email = (get_allowed_admin_email() or '').strip().lower()
            normalized_email = (email or '').strip().lower()

            logger.debug(
                f"Signup request: {full_name}, {email}, {phone_number}, role={role}"
            )

            # Required fields
            if not all([full_name, email, phone_number, password, confirm_password, role, terms]):
                flash("Fill in all required fields and accept terms.", "danger")
                return redirect(url_for("auth.signup"))

            if allowed_admin_email and normalized_email == allowed_admin_email:
                existing_admin_email = User.query.filter(User.email == email).first()
                if existing_admin_email and existing_admin_email.role != 'admin':
                    db.session.delete(existing_admin_email)
                    db.session.commit()
                    flash("The admin email is reserved and cannot be used for normal signups.", "danger")
                else:
                    flash("The admin email is reserved and cannot be used for normal signups.", "danger")
                return redirect(url_for("auth.signup"))

            # Role validation
            allowed_roles_raw = SystemSetting.get('signup_allowed_roles', 'tenant,landlord,service')
            allowed_roles = []
            for item in (allowed_roles_raw or '').split(','):
                clean_role = item.strip().lower()
                if clean_role in ['tenant', 'landlord', 'service'] and clean_role not in allowed_roles:
                    allowed_roles.append(clean_role)

            if not allowed_roles:
                allowed_roles = ['tenant', 'landlord', 'service']

            if role not in allowed_roles:
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

            flash("Account created. Please log in to receive your email verification code.", "success")
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

        if not getattr(user, 'email', None):
            flash("No email address is available for this account.", "danger")
            return render_template("forgot_password.html")

        _queue_password_reset(user)
        flash("Password reset link sent.", "success")
        logger.debug(f"Password reset requested for {identifier}")
        return redirect(url_for("auth.login"))

    return render_template("forgot_password.html")


# ------------------- RESET PASSWORD -------------------
@auth_bp.route("/reset_password/<token>", methods=["GET", "POST"])
def reset_password(token):
    try:
        user = _verify_password_reset_token(token)
    except SignatureExpired:
        flash("Password reset link expired. Please request a new one.", "warning")
        return redirect(url_for("auth.forgot_password"))
    except BadSignature:
        flash("Invalid password reset link.", "danger")
        return redirect(url_for("auth.forgot_password"))
    except Exception:
        logger.exception('Failed to verify password reset token')
        flash("Could not verify the password reset link.", "danger")
        return redirect(url_for("auth.forgot_password"))

    if not user:
        flash("Password reset link is no longer valid.", "danger")
        return redirect(url_for("auth.forgot_password"))

    if request.method == 'POST':
        password = request.form.get('password') or ''
        confirm_password = request.form.get('confirm_password') or ''

        if len(password) < 8:
            flash('Password must be at least 8 characters long.', 'danger')
            return render_template('reset_password.html', token=token, user=user)

        if password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return render_template('reset_password.html', token=token, user=user)

        user.set_password(password)
        db.session.commit()

        if user.role == 'admin':
            session.pop('admin_entry_granted', None)
            session.pop('admin_entry_granted_at', None)
            session.pop('admin_last_seen_at', None)
            session.pop('admin_session_nonce', None)
            session.pop('admin_id', None)
            session.pop('is_impersonating', None)
            clear_admin_totp_verification()

        flash('Password reset successfully. Please log in with your new password.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('reset_password.html', token=token, user=user)


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
    clear_admin_totp_verification()
    session.pop('admin_entry_granted', None)
    session.pop('admin_entry_granted_at', None)
    flash("Logged out successfully.", "info")
    return redirect(url_for("auth.login"))


# ------------------- PROFILE -------------------
@auth_bp.route("/profile")
@login_required
def profile():
    return render_template("profile.html", user=current_user)


@auth_bp.route('/admin-security-setup', methods=['GET', 'POST'])
@login_required
def admin_security_setup():
    if not is_approved_admin(current_user):
        flash("Access denied. Admins only.", "danger")
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        verification_code = (request.form.get('verification_code') or '').strip()
        secret = current_user.two_factor_secret

        if not secret:
            flash('Admin 2FA setup session expired. Please try again.', 'danger')
            return redirect(url_for('auth.admin_security_setup'))

        totp = pyotp.TOTP(secret)
        if totp.verify(verification_code):
            current_user.two_factor_enabled = True
            current_user.preferred_2fa_method = 'totp'
            db.session.commit()
            mark_admin_totp_verified(current_user)
            flash('Admin authenticator 2FA enabled successfully.', 'success')
            return redirect(url_for('admin.dashboard'))

        flash('Invalid verification code. Please try again.', 'danger')

    if not current_user.two_factor_secret:
        secret = pyotp.random_base32()
        current_user.two_factor_secret = secret
        db.session.commit()
    else:
        secret = current_user.two_factor_secret

    totp_uri = pyotp.totp.TOTP(secret).provisioning_uri(
        name=current_user.email,
        issuer_name='HomeHub'
    )
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(totp_uri)
    qr.make(fit=True)
    img = qr.make_image(fill='black', back_color='white')
    buffered = BytesIO()
    img.save(buffered)
    qr_code_b64 = base64.b64encode(buffered.getvalue()).decode('utf-8')

    return render_template(
        '2fa_setup.html',
        qr_code=qr_code_b64,
        secret=secret,
        setup_title='Admin Authenticator Setup',
        intro_text='Scan the QR code with Google Authenticator, Authy, or Microsoft Authenticator to secure the admin account.',
        back_url=url_for('admin.dashboard'),
        back_label='Admin Dashboard',
        email_option_url=None,
        email_option_text=None,
        show_email_option=False,
        post_url=url_for('auth.admin_security_setup'),
    )


@auth_bp.route('/admin-2fa-verify', methods=['GET', 'POST'])
@login_required
def admin_2fa_verify():
    if not is_approved_admin(current_user):
        flash("Access denied. Admins only.", "danger")
        return redirect(url_for('auth.login'))

    if not current_user.two_factor_enabled or not current_user.two_factor_secret:
        flash("Enable authenticator 2FA before accessing admin pages.", "warning")
        return redirect(url_for('auth.admin_security_setup'))

    if request.method == 'POST':
        code = (request.form.get('code') or '').strip()
        if not code:
            flash('Please enter your authenticator code.', 'danger')
            return render_template(
                'verify_2fa_login.html',
                method='totp',
                masked_email=current_user.email,
                resend_wait_seconds=0,
            )

        allowed, retry_after = consume_rate_limit(f"admin-totp:{current_user.id}", 5, 60)
        if not allowed:
            flash(f"Too many attempts. Please wait {retry_after}s and try again.", 'warning')
            return render_template(
                'verify_2fa_login.html',
                method='totp',
                masked_email=current_user.email,
                resend_wait_seconds=0,
            )

        totp = pyotp.TOTP(current_user.two_factor_secret)
        if totp.verify(code, valid_window=1):
            mark_admin_totp_verified(current_user)
            flash('Admin authenticator verification complete.', 'success')
            return redirect(url_for('admin.dashboard'))

        flash('Invalid authenticator code. Please try again.', 'danger')

    return render_template(
        'verify_2fa_login.html',
        method='totp',
        masked_email=current_user.email,
        resend_wait_seconds=0,
    )

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
        # Email 2FA is always tied to the account email stored in DB.
        if not current_user.email or not verify_email_format(current_user.email):
            flash("Your account email is invalid. Update your profile email first.", "danger")
            return redirect(url_for('auth.profile'))

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
    
    return render_template('setup_email_2fa.html', email_enabled=email_enabled, account_email=current_user.email)


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
            
            # Email 2FA should become the active preference when the user enables it
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

    def _resend_wait_seconds():
        allowed_at = int(session.get('otp_resend_allowed_at', 0) or 0)
        return max(0, allowed_at - int(time.time()))
    
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
            return render_template(
                'verify_2fa_login.html',
                method=method,
                masked_email=user.email[:3] + '***' + user.email[-10:],
                resend_wait_seconds=_resend_wait_seconds(),
            )
        
        # Check if backup code (starts with letter, 8 chars)
        if len(code) == 8 and code[0].isalpha():
            verification = user.two_factor_verification
            if verification and verification.use_backup_code(code):
                db.session.commit()
                session.pop('pending_2fa_user_id')
                session.pop('2fa_method')
                session.pop('otp_resend_allowed_at', None)
                login_user(user, remember=session.pop('remember_me', False))
                flash("Logged in with backup code. Please generate new backup codes.", "warning")
                logger.info(f"User {user.id} logged in with backup code")
                return redirect(url_for('auth.show_backup_codes'))
            else:
                flash("Invalid backup code.", "danger")
        
        # Regular OTP verification
        elif verify_code(user, code, method=method):
            session.pop('pending_2fa_user_id')
            session.pop('2fa_method')
            session.pop('otp_resend_allowed_at', None)
            login_user(user, remember=session.pop('remember_me', False))
            flash("Login successful.", "success")
            logger.info(f"User {user.id} logged in with {method} 2FA")
            
            # Redirect based on role
            if user.role == "tenant":
                return redirect(url_for("tenant.dashboard"))
            elif user.role == "landlord":
                return redirect(url_for("landlord.dashboard"))
            elif user.role == "service":
                return redirect(url_for("main.index"))
            elif user.role == "admin":
                # Keep the private admin entry session alive across the email OTP step.
                session['admin_entry_granted'] = True
                session['admin_entry_granted_at'] = int(time.time())
                session.modified = True

                if user.two_factor_enabled and user.two_factor_secret and not has_admin_totp_verified(user):
                    return redirect(url_for("auth.admin_2fa_verify"))

                return redirect(url_for("admin.dashboard"))
            else:
                return redirect(url_for("main.index"))
        else:
            flash("Invalid or expired code. Please request a new one.", "danger")
            return render_template(
                'verify_2fa_login.html',
                method=method,
                masked_email=user.email[:3] + '***' + user.email[-10:],
                resend_wait_seconds=_resend_wait_seconds(),
            )
    
    masked_email = user.email[:3] + '***' + user.email[-10:]
    return render_template(
        'verify_2fa_login.html',
        method=method,
        masked_email=masked_email,
        resend_wait_seconds=_resend_wait_seconds(),
    )


@auth_bp.route('/resend-2fa-login-code', methods=['POST'])
def resend_2fa_login_code():
    """Resend login OTP to account email with cooldown protection."""
    user_id = session.get('pending_2fa_user_id')
    method = session.get('2fa_method', 'email')

    if not user_id:
        flash("Your login session expired. Please log in again.", "warning")
        return redirect(url_for('auth.login'))

    user = User.query.get(user_id)
    if not user:
        session.pop('pending_2fa_user_id', None)
        session.pop('2fa_method', None)
        session.pop('otp_resend_allowed_at', None)
        flash("User not found. Please log in again.", "danger")
        return redirect(url_for('auth.login'))

    now = int(time.time())
    allowed_at = int(session.get('otp_resend_allowed_at', 0) or 0)
    if now < allowed_at:
        wait_seconds = allowed_at - now
        flash(f"Please wait {wait_seconds}s before requesting a new code.", "warning")
        return redirect(url_for('auth.verify_2fa_login'))

    code_obj = create_verification_code(user, method=method)
    if send_2fa_email(user.email, user.name, code_obj.code, method='login'):
        session['otp_resend_allowed_at'] = int(time.time()) + 30
        flash("A new login code has been sent to your email.", "info")
    else:
        flash("Could not resend code right now. Please try again.", "danger")

    return redirect(url_for('auth.verify_2fa_login'))


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
                          enabled_methods=enabled_methods,
                          approved_admin_email=get_allowed_admin_email(),
                          is_admin_account=is_approved_admin(current_user),
                          admin_totp_verified=has_admin_totp_verified(current_user))


# ================ VERIFY 2FA (Legacy TOTP) ================
def verify_2fa_code(user, code):
    if not user.two_factor_secret:
        return False
    totp = pyotp.TOTP(user.two_factor_secret)
    return totp.verify(code)


@auth_bp.route('/social-login/<provider>')
def social_login(provider):
    return f"Social login with {provider} coming soon"