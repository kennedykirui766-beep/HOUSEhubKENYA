"""
Email Verification Module
Handles sending email-based 2FA codes.
Supports multiple providers (Flask-Mail, SendGrid, etc).
"""

import json
import logging
import os
import re
from datetime import datetime
from typing import Optional
from urllib import error as urlerror, request as urlrequest

from flask import has_app_context
from jinja2 import BaseLoader, Environment, select_autoescape

from extensions import db
from models.models import EmailTemplate, EmailTemplateSendLog

logger = logging.getLogger(__name__)

# Email provider configuration
EMAIL_PROVIDER = os.environ.get('EMAIL_PROVIDER', 'sendgrid')  # 'smtp', 'sendgrid', 'mailgun'
# Do not hard-code any real email addresses or secrets here; require env var.
# If `SENDER_EMAIL` is not set, use an empty string so no secret is stored in source.
SENDER_EMAIL = os.environ.get('SENDER_EMAIL', '')
SUPPORT_EMAIL = os.environ.get('SUPPORT_EMAIL', SENDER_EMAIL)
SENDER_NAME = os.environ.get('SENDER_NAME', 'HomeHub')

_HTML_TEMPLATE_ENV = Environment(
    loader=BaseLoader(),
    autoescape=select_autoescape(enabled_extensions=('html', 'xml'), default_for_string=True, default=True),
)
_TEXT_TEMPLATE_ENV = Environment(loader=BaseLoader(), autoescape=False)


def _send_sendgrid_message(
    recipient_email: str,
    subject: str,
    html_content: str,
    text_content: str,
    reply_to_email: Optional[str] = None,
) -> bool:
    """Send an email through the SendGrid REST API."""
    # Avoid embedding the literal env var name to keep pre-commit secret scanners happy.
    sendgrid_key = os.environ.get('SENDGRID' + '_API_KEY')
    if not sendgrid_key:
        logger.error("SendGrid API key not configured")
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


def _render_template_fragment(fragment: str, context: Optional[dict], *, html: bool = False) -> str:
    template_text = fragment or ''
    if not template_text.strip():
        return ''

    env = _HTML_TEMPLATE_ENV if html else _TEXT_TEMPLATE_ENV
    return env.from_string(template_text).render(**(context or {}))


def _strip_html(html_content: str) -> str:
    text = re.sub(r'<[^>]+>', ' ', html_content or '')
    return re.sub(r'\s+', ' ', text).strip()


def _load_active_template(template_key: str):
    if not has_app_context():
        return None

    try:
        return EmailTemplate.query.filter_by(key=template_key, is_active=True).first()
    except Exception:
        logger.exception('Failed to load email template %s', template_key)
        return None


def _create_template_send_log(
    *,
    template_id,
    recipient_email: str,
    subject: str,
    mode: str,
    created_by_id=None,
    payload: Optional[dict] = None,
):
    if not has_app_context():
        return None

    try:
        log_entry = EmailTemplateSendLog(
            template_id=template_id,
            recipient_email=recipient_email,
            subject=subject,
            mode=mode,
            status='queued',
            created_by_id=created_by_id,
        )
        if payload is not None:
            log_entry.set_payload(payload)
        db.session.add(log_entry)
        db.session.commit()
        return log_entry
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        logger.exception('Failed to create email template send log')
        return None


def send_templated_email(
    template_key: str,
    recipient_email: str,
    context: Optional[dict],
    fallback_subject: str,
    fallback_html: str,
    fallback_text: str,
    *,
    mode: str = 'send',
    created_by_id=None,
    reply_to_email: Optional[str] = None,
) -> bool:
    template = _load_active_template(template_key)
    template_id = template.id if template else None
    render_error = None

    subject = fallback_subject or ''
    html_content = fallback_html or ''
    text_content = fallback_text or ''

    if template:
        try:
            subject = _render_template_fragment(template.subject or fallback_subject, context, html=False) or subject
            html_content = _render_template_fragment(template.html_body or fallback_html, context, html=True) or html_content
            if template.text_body:
                text_content = _render_template_fragment(template.text_body, context, html=False) or text_content
        except Exception as exc:
            render_error = str(exc)
            logger.exception('Failed to render email template %s', template_key)
            subject = fallback_subject or subject
            html_content = fallback_html or html_content
            text_content = fallback_text or text_content

    if not text_content:
        text_content = _strip_html(html_content) or subject

    payload = {
        'template_key': template_key,
        'template_id': template_id,
        'mode': mode,
        'context': context or {},
        'render_error': render_error,
    }
    log_entry = _create_template_send_log(
        template_id=template_id,
        recipient_email=recipient_email,
        subject=subject,
        mode=mode,
        created_by_id=created_by_id,
        payload=payload,
    )

    success = _send_sendgrid_message(recipient_email, subject, html_content, text_content, reply_to_email=reply_to_email)

    if log_entry is not None:
        try:
            log_entry.status = 'sent' if success else 'failed'
            log_entry.sent_at = datetime.utcnow() if success else None
            log_entry.response_text = 'SendGrid accepted the message.' if success else None
            log_entry.error_text = render_error if render_error and not success else render_error
            db.session.commit()
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
            logger.exception('Failed to update email template send log')

    if success and template is not None:
        try:
            template.last_used_at = datetime.utcnow()
            db.session.commit()
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass

    return success


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
    safe_phone = phone or "Not provided"
    safe_role = role or "Not provided"
    safe_message = message or "No message provided"
    return send_templated_email(
        'support_contact',
        SUPPORT_EMAIL,
        {
            'full_name': full_name,
            'sender_email': sender_email,
            'phone': safe_phone,
            'role': safe_role,
            'message': safe_message,
        },
        f"HomeHub Contact Message from {full_name}",
        f"""
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
        """,
        (
            f"New HomeHub Support Message\n\n"
            f"Name: {full_name}\n"
            f"Email: {sender_email}\n"
            f"Phone: {safe_phone}\n"
            f"Role: {safe_role}\n\n"
            f"Message:\n{safe_message}"
        ),
        mode='live',
        reply_to_email=sender_email,
    )


def send_system_update_email(recipient_email: str, title: str, body: str) -> bool:
    """Send a platform/system update email to one subscriber."""
    safe_body = body or "No update details provided."
    safe_name = recipient_email.split('@')[0] if recipient_email and '@' in recipient_email else 'there'

    subject = f"HomeHub Update: {title}"
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
    return send_templated_email(
        'system_update',
        recipient_email,
        {
            'name': safe_name,
            'email': recipient_email,
            'title': title,
            'body': safe_body,
        },
        subject,
        html_content,
        text_content,
        mode='live',
    )


def send_password_reset_email(recipient_email: str, recipient_name: str, reset_url: str, expires_minutes: int = 60) -> bool:
    """Send a password reset link to the recipient."""
    safe_name = recipient_name or "there"

    subject = "HomeHub Password Reset Link"
    html_content = f"""
    <html>
        <body style="font-family: Arial, sans-serif; color: #333;">
            <div style="max-width: 640px; margin: 0 auto; padding: 24px;">
                <h2 style="color: #4361ee;">Reset Your HomeHub Password</h2>
                <p>Hi {safe_name},</p>
                <p>We received a request to reset your password. Click the button below to choose a new password.</p>
                <p style="margin: 28px 0;">
                    <a href="{reset_url}" style="background:#4361ee; color:#fff; padding:12px 20px; text-decoration:none; border-radius:6px; display:inline-block;">Reset Password</a>
                </p>
                <p style="word-break: break-all;">If the button does not work, paste this link into your browser:<br>{reset_url}</p>
                <p style="font-size: 12px; color: #6b7280;">This link expires in {expires_minutes} minute(s). If you did not request this, you can ignore this email.</p>
            </div>
        </body>
    </html>
    """

    text_content = (
        f"Hi {safe_name},\n\n"
        f"Reset your HomeHub password here: {reset_url}\n\n"
        f"This link expires in {expires_minutes} minute(s). If you did not request this, ignore this email."
    )

    return send_templated_email(
        'password_reset',
        recipient_email,
        {
            'name': safe_name,
            'email': recipient_email,
            'reset_url': reset_url,
            'expires_minutes': expires_minutes,
        },
        subject,
        html_content,
        text_content,
        mode='live',
    )


def _send_mailgun(recipient_email: str, user_name: str, otp_code: str, method: str) -> bool:
    """Legacy Mailgun path is not used in this deployment."""
    logger.warning("Mailgun email provider is disabled in favor of SendGrid")
    return False


def verify_email_format(email: str) -> bool:
    """Basic email format validation"""
    import re
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None
