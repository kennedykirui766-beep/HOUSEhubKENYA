from flask_mail import Message

def send_payment_email(to_email, tenant_name, payment_url, amount):
    msg = Message(
        subject="Deposit Payment Request",
        recipients=[to_email]
    )

    # ✅ PUT IT HERE (inside the function)
    msg.html = f"""
    <h3>Hello {tenant_name},</h3>

    <p>You have a deposit payment request.</p>

    <p><strong>Amount:</strong> KES {amount}</p>

    <p>
        <a href="{payment_url}" 
           style="padding:10px 15px; background:#28a745; color:white; text-decoration:none;">
            Pay Now
        </a>
    </p>

    <p>Thank you.</p>
    """

    mail.send(msg)