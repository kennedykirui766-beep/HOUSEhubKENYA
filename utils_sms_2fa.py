"""
SMS OTP Module
Handles sending SMS-based 2FA codes via Twilio.
"""

import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Twilio configuration
TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN')
TWILIO_FROM_NUMBER = os.environ.get('TWILIO_FROM_NUMBER')


def is_twilio_configured() -> bool:
    """Check if Twilio is properly configured"""
    return bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_FROM_NUMBER)


def send_2fa_sms(phone_number: str, user_name: str, otp_code: str) -> bool:
    """
    Send 2FA verification SMS with OTP code via Twilio.
    
    Args:
        phone_number: Phone number to send to (E.164 format: +254...)
        user_name: User's display name
        otp_code: The OTP code to include
    
    Returns:
        bool: True if SMS sent successfully
    """
    
    if not is_twilio_configured():
        logger.error("Twilio not configured. Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER")
        return False
    
    try:
        from twilio.rest import Client
        
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        
        message_body = f"""HomeHub 2FA Code: {otp_code}
        
This code expires in 5 minutes. Do not share this code.

If you didn't request this, ignore this message."""
        
        message = client.messages.create(
            body=message_body,
            from_=TWILIO_FROM_NUMBER,
            to=phone_number
        )
        
        logger.info(f"2FA SMS sent to {phone_number} (SID: {message.sid})")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send SMS via Twilio: {str(e)}")
        return False


def validate_phone_number(phone_number: str) -> bool:
    """
    Validate phone number format (E.164 format).
    Accepts formats like: +254712345678, +1234567890, etc.
    """
    import re
    # E.164 format: + followed by 1-15 digits
    pattern = r'^\+[1-9]\d{1,14}$'
    return re.match(pattern, phone_number) is not None


def format_phone_number(phone: str, country_code: str = "254") -> Optional[str]:
    """
    Format phone number to E.164 format.
    
    Args:
        phone: Phone number (can be various formats)
        country_code: Default country code (Kenya = 254)
    
    Returns:
        str: E.164 formatted number, or None if invalid
    """
    import re
    
    # Remove all non-digits
    digits = re.sub(r'\D', '', phone)
    
    # If number starts with 0 (local format), replace with country code
    if digits.startswith('0'):
        digits = country_code + digits[1:]
    # If number doesn't have country code, add it
    elif not digits.startswith(country_code) and len(digits) == 9:
        digits = country_code + digits
    # If number starts with country code digits, ensure it's there
    elif not digits.startswith(country_code):
        digits = country_code + digits
    
    # Format as E.164
    formatted = '+' + digits
    
    if validate_phone_number(formatted):
        return formatted
    
    return None


def mask_phone_number(phone_number: str) -> str:
    """
    Mask phone number for display (e.g., +254***5678).
    Used in UI to show partial number without exposing full details.
    """
    if not phone_number or len(phone_number) < 4:
        return "****"
    
    return phone_number[:4] + "***" + phone_number[-4:]


def send_sms_verification_code(phone_number: str, otp_code: str) -> bool:
    """
    Send SMS for initial phone number verification (not 2FA).
    Used during 2FA setup.
    """
    try:
        from twilio.rest import Client
        
        if not is_twilio_configured():
            logger.error("Twilio not configured")
            return False
        
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        
        message_body = f"""HomeHub Verification Code: {otp_code}

This code expires in 15 minutes.
Do not share this code with anyone."""
        
        message = client.messages.create(
            body=message_body,
            from_=TWILIO_FROM_NUMBER,
            to=phone_number
        )
        
        logger.info(f"Verification SMS sent to {phone_number}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send verification SMS: {str(e)}")
        return False


def get_sms_credits_info() -> dict:
    """
    Get Twilio account info (optional, for monitoring).
    Returns dict with account details.
    """
    try:
        from twilio.rest import Client
        
        if not is_twilio_configured():
            return {"error": "Twilio not configured"}
        
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        account = client.api.accounts(TWILIO_ACCOUNT_SID).fetch()
        
        return {
            "account_sid": account.sid,
            "friendly_name": account.friendly_name,
            "status": account.status,
            "date_created": str(account.date_created),
            "date_updated": str(account.date_updated)
        }
        
    except Exception as e:
        logger.error(f"Failed to get Twilio info: {str(e)}")
        return {"error": str(e)}
