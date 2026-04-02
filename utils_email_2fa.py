"""
Email Verification Module
Handles sending email-based 2FA codes.
Supports multiple providers (Flask-Mail, SendGrid, etc).
"""

import os
import logging
from typing import Optional
from flask import render_template_string

logger = logging.getLogger(__name__)

# Email provider configuration
EMAIL_PROVIDER = os.environ.get('EMAIL_PROVIDER', 'smtp')  # 'smtp', 'sendgrid', 'mailgun'
SENDER_EMAIL = os.environ.get('SENDER_EMAIL', 'noreply@homehub.app')
SENDER_NAME = os.environ.get('SENDER_NAME', 'HomeHub')


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
    """Send email via SMTP (requires Flask-Mail setup)"""
    try:
        from flask_mail import Mail, Message
        from app import app
        
        mail = Mail(app)
        
        subject = f"Your HomeHub 2FA Code: {otp_code}"
        
        html_body = f"""
        <html>
            <body style="font-family: Arial, sans-serif; color: #333;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                    <h2 style="color: #4361ee;">HomeHub 2FA Verification</h2>
                    
                    <p>Hi {user_name},</p>
                    
                    <p>Your 2-Factor Authentication code is:</p>
                    
                    <div style="background-color: #f0f0f0; padding: 15px; border-radius: 5px; text-align: center;">
                        <h1 style="letter-spacing: 5px; color: #4361ee; margin: 0;">{otp_code}</h1>
                    </div>
                    
                    <p style="color: #666; margin-top: 20px;">
                        <strong>⏱️ This code expires in 5 minutes.</strong>
                    </p>
                    
                    <p style="color: #999; font-size: 12px;">
                        If you didn't request this code, ignore this email. Your account is secure.
                    </p>
                    
                    <hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;">
                    
                    <p style="color: #999; font-size: 11px;">
                        HomeHub Security Team<br>
                        This is an automated message, please do not reply.
                    </p>
                </div>
            </body>
        </html>
        """
        
        msg = Message(
            subject=subject,
            sender=(SENDER_NAME, SENDER_EMAIL),
            recipients=[recipient_email],
            html=html_body
        )
        
        mail.send(msg)
        logger.info(f"2FA email sent to {recipient_email}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send SMTP email: {str(e)}")
        return False


def _send_sendgrid(recipient_email: str, user_name: str, otp_code: str, method: str) -> bool:
    """Send email via SendGrid API"""
    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail, Email, To, Content
        
        sendgrid_key = os.environ.get('SENDGRID_API_KEY')
        if not sendgrid_key:
            logger.error("SENDGRID_API_KEY not configured")
            return False
        
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
        
        message = Mail(
            from_email=(SENDER_EMAIL, SENDER_NAME),
            to_emails=To(recipient_email),
            subject=subject,
            html_content=html_content
        )
        
        sg = SendGridAPIClient(sendgrid_key)
        response = sg.send(message)
        
        if response.status_code in [200, 201, 202]:
            logger.info(f"2FA email sent via SendGrid to {recipient_email}")
            return True
        else:
            logger.error(f"SendGrid error: {response.status_code}")
            return False
            
    except Exception as e:
        logger.error(f"Failed to send SendGrid email: {str(e)}")
        return False


def _send_mailgun(recipient_email: str, user_name: str, otp_code: str, method: str) -> bool:
    """Send email via Mailgun API"""
    try:
        import requests
        
        mailgun_domain = os.environ.get('MAILGUN_DOMAIN')
        mailgun_key = os.environ.get('MAILGUN_API_KEY')
        
        if not mailgun_domain or not mailgun_key:
            logger.error("Mailgun credentials not configured")
            return False
        
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
        
        response = requests.post(
            f"https://api.mailgun.net/v3/{mailgun_domain}/messages",
            auth=("api", mailgun_key),
            data={
                "from": f"{SENDER_NAME} <{SENDER_EMAIL}>",
                "to": recipient_email,
                "subject": subject,
                "html": html_content
            }
        )
        
        if response.status_code == 200:
            logger.info(f"2FA email sent via Mailgun to {recipient_email}")
            return True
        else:
            logger.error(f"Mailgun error: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"Failed to send Mailgun email: {str(e)}")
        return False


def verify_email_format(email: str) -> bool:
    """Basic email format validation"""
    import re
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None
