"""
Email Verification Module
Handles sending email-based 2FA codes.
Supports multiple providers (Flask-Mail, SendGrid, etc).
"""

import json
import logging
import os
from typing import Optional
from urllib import error as urlerror, request as urlrequest

logger = logging.getLogger(__name__)

# Email provider configuration
EMAIL_PROVIDER = os.environ.get('EMAIL_PROVIDER', 'sendgrid')  # 'smtp', 'sendgrid', 'mailgun'
SENDER_EMAIL = os.environ.get('SENDER_EMAIL', 'kamauemilio466@gmail.com')
SUPPORT_EMAIL = os.environ.get('SUPPORT_EMAIL', SENDER_EMAIL)
SENDER_NAME = os.environ.get('SENDER_NAME', 'HomeHub')


def _send_sendgrid_message(
    recipient_email: str,
    subject: str,
    html_content: str,
    text_content: str,
    reply_to_email: Optional[str] = None,
) -> bool:
    """Send an email through the SendGrid REST API."""
    sendgrid_key = os.environ.get('SENDGRID_API_KEY')
    if not sendgrid_key:
        logger.error("SENDGRID_API_KEY not configured")
        return False

    payload = {
        "personalizations": [
            {
                "to": [{"email": recipient_email}],
            }
        ],
        "from": {"email": SENDER_EMAIL, "name": SENDER_NAME},
        "subject": subject,
        "content": [
            {"type": "text/plain", "value": text_content},
            {"type": "text/html", "value": html_content},
        ],
    }

    if reply_to_email:
        payload["reply_to"] = {"email": reply_to_email}

    request = urlrequest.Request(
        "https://api.sendgrid.com/v3/mail/send",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {sendgrid_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urlrequest.urlopen(request, timeout=20) as response:
            if response.status in (200, 201, 202):
                return True
            logger.error(f"SendGrid error: {response.status}")
            return False
    except urlerror.HTTPError as exc:
        logger.error(f"SendGrid HTTP error: {exc.code} - {exc.read().decode('utf-8', errors='ignore')}")
        return False
    except Exception as exc:
        logger.error(f"Failed to send SendGrid email: {str(exc)}")
        return False


def send_2fa_email(recipient_email: str, user_name: str, otp_code: str, method: str = 'email') -> bool:
    """
    Send 2FA verification email with OTP code.
    
    Args:
        recipient_email: Email address to send to
        user_name: User's display name
        otp_code: The OTP code to include
        method: Type of 2FA (for contexts like 'verify_email', 'enable_2fa', etc)
    
    Returns:
        bool: True if email sent successfully
    """
    
    if EMAIL_PROVIDER == 'smtp':
        return _send_smtp(recipient_email, user_name, otp_code, method)
    elif EMAIL_PROVIDER == 'sendgrid':
        return _send_sendgrid(recipient_email, user_name, otp_code, method)
    elif EMAIL_PROVIDER == 'mailgun':
        return _send_mailgun(recipient_email, user_name, otp_code, method)
    else:
        logger.error(f"Unknown email provider: {EMAIL_PROVIDER}")
        return False


def _send_smtp(recipient_email: str, user_name: str, otp_code: str, method: str) -> bool:
    """Legacy SMTP path is not used in this deployment."""
    logger.warning("SMTP email provider is disabled in favor of SendGrid")
    return False


def _send_sendgrid(recipient_email: str, user_name: str, otp_code: str, method: str) -> bool:
    """Send email via SendGrid REST API"""
    subject = f"Your HomeHub 2FA Code: {otp_code}"

    html_content = f"""
    <html>
        <body style="font-family: Arial, sans-serif; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: #4361ee;">HomeHub 2FA Verification</h2>
                <p>Hi {user_name},</p>
                <p>Your 2-Factor Authentication code is:</p>
                <div style="background-color: #f0f0f0; padding: 15px; border-radius: 5px; text-align: center;">
                    <h1 style="letter-spacing: 5px; color: #4361ee; margin: 0;">{otp_code}</h1>
                </div>
                <p style="color: #666; margin-top: 20px;"><strong>⏱️ This code expires in 5 minutes.</strong></p>
                <p style="color: #999; font-size: 12px;">If you didn't request this code, ignore this email. Your account is secure.</p>
            </div>
        </body>
    </html>
    """

    text_content = (
        f"Hi {user_name},\n\n"
        f"Your HomeHub 2FA code is: {otp_code}\n"
        "This code expires in 5 minutes.\n\n"
        "If you didn't request this code, ignore this email."
    )

    success = _send_sendgrid_message(recipient_email, subject, html_content, text_content)
    if success:
        logger.info(f"2FA email sent via SendGrid to {recipient_email}")
    return success


def send_support_contact_email(full_name: str, sender_email: str, phone: str, role: str, message: str) -> bool:
    """Send a contact/support message to the configured support inbox via SendGrid."""
    subject = f"HomeHub Contact Message from {full_name}"

    safe_phone = phone or "Not provided"
    safe_role = role or "Not provided"
    safe_message = message or "No message provided"

    html_content = f"""
    <html>
        <body style="font-family: Arial, sans-serif; color: #333;">
            <div style="max-width: 640px; margin: 0 auto; padding: 24px;">
                <h2 style="color: #4361ee;">New HomeHub Support Message</h2>
                <p><strong>Name:</strong> {full_name}</p>
                <p><strong>Email:</strong> {sender_email}</p>
                <p><strong>Phone:</strong> {safe_phone}</p>
                <p><strong>Role:</strong> {safe_role}</p>
                <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 20px 0;">
                <p style="white-space: pre-wrap;"><strong>Message:</strong><br>{safe_message}</p>
            </div>
        </body>
    </html>
    """

    text_content = (
        f"New HomeHub Support Message\n\n"
        f"Name: {full_name}\n"
        f"Email: {sender_email}\n"
        f"Phone: {safe_phone}\n"
        f"Role: {safe_role}\n\n"
        f"Message:\n{safe_message}"
    )

    return _send_sendgrid_message(
        SUPPORT_EMAIL,
        subject,
        html_content,
        text_content,
        reply_to_email=sender_email,
    )


def send_system_update_email(recipient_email: str, title: str, body: str) -> bool:
        """Send a platform/system update email to one subscriber."""
        subject = f"HomeHub Update: {title}"
        safe_body = body or "No update details provided."

        html_content = f"""
        <html>
            <body style="font-family: Arial, sans-serif; color: #333;">
                <div style="max-width: 640px; margin: 0 auto; padding: 24px;">
                    <h2 style="color: #4361ee; margin-bottom: 12px;">{title}</h2>
                    <div style="white-space: pre-wrap; line-height: 1.6;">{safe_body}</div>
                    <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 20px 0;">
                    <p style="font-size: 12px; color: #6b7280;">
                        You are receiving this because you subscribed to HomeHub system updates.
                    </p>
                </div>
            </body>
        </html>
        """

        text_content = f"{title}\n\n{safe_body}\n\nYou are receiving this because you subscribed to HomeHub system updates."
        return _send_sendgrid_message(recipient_email, subject, html_content, text_content)


def _send_mailgun(recipient_email: str, user_name: str, otp_code: str, method: str) -> bool:
    """Legacy Mailgun path is not used in this deployment."""
    logger.warning("Mailgun email provider is disabled in favor of SendGrid")
    return False


def verify_email_format(email: str) -> bool:
    """Basic email format validation"""
    import re
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None
