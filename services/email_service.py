from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
import os

def send_payment_email(to_email, tenant_name, payment_url, amount):
    # Define styles directly in the HTML string for maximum compatibility
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Payment Request</title>
        <style>
            /* Minimal reset for email clients */
            body {{ margin: 0; padding: 0; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; }}
            a {{ text-decoration: none; }}
        </style>
    </head>
    <body style="background-color: #f4f4f7; margin: 0; padding: 0; -webkit-font-smoothing: antialiased;">
        
        <!-- Outer Container: Centers the email and adds background color -->
        <table border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color: #f4f4f7;">
            <tr>
                <td align="center" style="padding: 40px 0;">
                    
                    <!-- Main Card: Max width 600px, White background, Shadow -->
                    <table border="0" cellpadding="0" cellspacing="0" width="600" style="background-color: #ffffff; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); overflow: hidden;">
                        
                        <!-- Header / Brand Area -->
                        <tr>
                            <td align="center" style="background-color: #007bff; padding: 30px 0;">
                                <h1 style="color: #ffffff; margin: 0; font-size: 24px; font-weight: 600; letter-spacing: 0.5px;">
                                    Secure Payment Request
                                </h1>
                            </td>
                        </tr>

                        <!-- Content Area -->
                        <tr>
                            <td style="padding: 40px 30px;">
                                
                                <!-- Greeting -->
                                <p style="font-size: 16px; color: #51545e; margin: 0 0 20px 0; line-height: 1.6;">
                                    Hello <strong>{tenant_name}</strong>,
                                </p>
                                
                                <!-- Main Message -->
                                <p style="font-size: 16px; color: #51545e; margin: 0 0 30px 0; line-height: 1.6;">
                                    We have received a new deposit request for your account. Please complete the payment below to confirm your booking.
                                </p>

                                <!-- Amount Box (Highlight) -->
                                <table border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color: #f0f7ff; border-radius: 6px; margin-bottom: 30px;">
                                    <tr>
                                        <td align="center" style="padding: 20px;">
                                            <p style="margin: 0 0 5px 0; color: #007bff; font-size: 14px; font-weight: 600; text-transform: uppercase; letter-spacing: 1px;">
                                                Total Amount Due
                                            </p>
                                            <p style="margin: 0; color: #333333; font-size: 32px; font-weight: bold;">
                                                KES {amount}
                                            </p>
                                        </td>
                                    </tr>
                                </table>

                                <!-- Call to Action Button -->
                                <table border="0" cellpadding="0" cellspacing="0" width="100%">
                                    <tr>
                                        <td align="center">
                                            <a href="{payment_url}" target="_blank" style="background-color: #28a745; color: #ffffff; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; font-size: 18px; font-weight: bold; padding: 14px 30px; border-radius: 5px; text-decoration: none; display: inline-block; box-shadow: 0 2px 4px rgba(40, 167, 69, 0.3);">
                                                Pay Now
                                            </a>
                                        </td>
                                    </tr>
                                </table>
                                
                                <!-- Alternative Text -->
                                <p style="font-size: 14px; color: #888888; text-align: center; margin-top: 20px;">
                                    If the button above doesn't work, copy and paste this link into your browser:<br>
                                    <a href="{payment_url}" style="color: #007bff; word-break: break-all;">{payment_url}</a>
                                </p>

                            </td>
                        </tr>

                        <!-- Footer -->
                        <tr>
                            <td align="center" style="padding: 20px; background-color: #f8f9fa; border-top: 1px solid #e9ecef;">
                                <p style="margin: 0; font-size: 12px; color: #999999;">
                                    Need help? Contact our support team.
                                </p>
                            </td>
                        </tr>

                    </table>
                    <!-- End Main Card -->
                    
                    <p style="text-align: center; font-size: 12px; color: #aaaaaa; margin-top: 20px;">
                        &copy; 2026 Your HOUSEhubKENYA. All rights reserved.
                    </p>

                </td>
            </tr>
        </table>
        
    </body>
    </html>
    """

    message = Mail(
        from_email="SENDER_EMAIL",
        to_emails=to_email,
        subject="Action Required: Deposit Payment Request",
        html_content=html_content
    )

    try:
        sg = SendGridAPIClient(os.environ.get("SENDGRID_API_KEY"))
        sg.send(message)
        return True
    except Exception as e:
        print(f"Error sending email: {e}")
        return False