from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Email
import os

def send_payment_email(to_email, tenant_name, payment_url, amount):
    message = Mail(
        from_email=Email(
            email=os.environ.get("SENDER_EMAIL"),
            name="HouseHub Kenya"
        ),
        to_emails=to_email,
        subject="Deposit Payment Request",
        html_content=f"""
        <h3>Hello {tenant_name},</h3>
        <p>You have a deposit payment request.</p>
        <p><strong>Amount:</strong> KES {amount}</p>
        <p><a href="{payment_url}">Pay Now</a></p>
        """
    )

    try:
        sg = SendGridAPIClient(os.environ.get("SENDGRID_API_KEY"))
        response = sg.send(message)

        print("✅ EMAIL SENT", response.status_code)

    except Exception as e:
        import traceback
        print("❌ FULL SENDGRID ERROR:")
        traceback.print_exc()

        if hasattr(e, 'body'):
            print("❌ SENDGRID RESPONSE BODY:", e.body)

        raise