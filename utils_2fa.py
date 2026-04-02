"""
2FA Utilities Module
Handles OTP generation, validation, and cleanup logic.
"""

import random
import string
from datetime import datetime, timedelta
from models.models import TwoFactorCode, TwoFactorVerification
from extensions import db
import logging

logger = logging.getLogger(__name__)

OTP_LENGTH = 6  # 6-digit OTP
OTP_TIMEOUT_SECONDS = 300  # 5 minutes
MAX_ATTEMPTS = 5  # Max verification attempts before blocking


def generate_otp(length=OTP_LENGTH):
    """Generate a random OTP code"""
    return ''.join(random.choices(string.digits, k=length))


def create_verification_code(user, method='email'):
    """
    Create a new verification code for user.
    
    Args:
        user: User object
        method: 'email' or 'sms'
    
    Returns:
        TwoFactorCode object
    """
    # Clean up old expired codes
    cleanup_expired_codes(user.id)
    
    code = generate_otp()
    expires_at = datetime.utcnow() + timedelta(seconds=OTP_TIMEOUT_SECONDS)
    
    two_fa_code = TwoFactorCode(
        user_id=user.id,
        code=code,
        method=method,
        expires_at=expires_at
    )
    
    db.session.add(two_fa_code)
    db.session.commit()
    
    logger.info(f"Generated {method} OTP for user {user.id}")
    return two_fa_code


def verify_code(user, code, method='email'):
    """
    Verify a 2FA code.
    
    Args:
        user: User object
        code: Code to verify (string)
        method: 'email' or 'sms'
    
    Returns:
        bool: True if code is valid
    """
    # Get valid codes
    valid_codes = TwoFactorCode.query.filter_by(
        user_id=user.id,
        code=code,
        method=method,
        is_used=False
    ).all()
    
    for code_obj in valid_codes:
        if code_obj.is_valid():  # Checks expiry
            code_obj.is_used = True
            db.session.commit()
            logger.info(f"Verified {method} OTP for user {user.id}")
            return True
    
    logger.warning(f"Failed OTP verification attempt for user {user.id}")
    return False


def get_active_code(user, method='email'):
    """Get the most recent active (unused, not expired) code"""
    return TwoFactorCode.query.filter_by(
        user_id=user.id,
        method=method,
        is_used=False
    ).filter(
        TwoFactorCode.expires_at > datetime.utcnow()
    ).order_by(TwoFactorCode.created_at.desc()).first()


def cleanup_expired_codes(user_id):
    """Delete expired codes for a user"""
    expired = TwoFactorCode.query.filter(
        TwoFactorCode.user_id == user_id,
        TwoFactorCode.expires_at <= datetime.utcnow()
    ).delete()
    
    if expired > 0:
        db.session.commit()
        logger.debug(f"Cleaned up {expired} expired codes for user {user_id}")


def cleanup_all_expired_codes():
    """Delete all expired codes (cleanup task)"""
    expired = TwoFactorCode.query.filter(
        TwoFactorCode.expires_at <= datetime.utcnow()
    ).delete()
    
    if expired > 0:
        db.session.commit()
        logger.info(f"Cleaned up {expired} expired codes globally")


def get_or_create_2fa_verification(user):
    """
    Get or create TwoFactorVerification record for user.
    Called during 2FA setup.
    """
    verification = TwoFactorVerification.query.filter_by(user_id=user.id).first()
    
    if not verification:
        verification = TwoFactorVerification(user_id=user.id)
        db.session.add(verification)
        db.session.commit()
    
    return verification


def generate_backup_codes(count=10):
    """
    Generate backup codes for recovery.
    Returns comma-separated string.
    """
    codes = []
    for _ in range(count):
        # Generate 8-character alphanumeric codes
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        codes.append(code)
    
    return ','.join(codes)


def has_valid_2fa_method(user):
    """Check if user has any active 2FA method enabled"""
    verification = user.two_factor_verification
    if not verification:
        return False
    
    return verification.is_any_method_enabled()


def get_enabled_2fa_methods(user):
    """Return list of enabled 2FA methods"""
    verification = user.two_factor_verification
    if not verification:
        return []
    
    methods = []
    if verification.email_enabled:
        methods.append('email')
    if verification.sms_enabled:
        methods.append('sms')
    if verification.totp_enabled:
        methods.append('totp')
    
    return methods


def log_2fa_event(user_id, event_type, details=""):
    """Log 2FA events for security auditing"""
    logger.info(f"2FA Event - User: {user_id}, Type: {event_type}, Details: {details}")
