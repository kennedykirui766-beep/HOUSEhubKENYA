from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
import os

def send_payment_email(to_email, tenant_name, payment_url, amount):
    message = Mail(
        from_email="SENDER_EMAIL",
        to_emails=to_email,
        subject="Deposit Payment Request",
        html_content=f"""
        <h3>Hello {tenant_name},</h3>
        <p>You have a deposit payment request.</p>
        <p><strong>Amount:</strong> KES {amount}</p>
        <p><a href="{payment_url}">Pay Now</a></p>
        """
    )

    sg = SendGridAPIClient(os.environ.get("SENDGRID_API_KEY"))
    sg.send(message)