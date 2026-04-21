from datetime import datetime
import os
from mailjet_rest import Client

def send_payment_email(to_email, tenant_name, payment_url, amount):
    """
    Sends a detailed, styled HTML email for a payment request.
    """
    
    # Branding details
    brand_name = "HouseHub Kenya"
    brand_color = "#0056b3"  # A professional deep blue
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Payment Request</title>
        <style>
            body {{ margin: 0; padding: 0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f6f8; }}
            a {{ text-decoration: none; }}
        </style>
    </head>
    <body style="background-color: #f4f6f8; margin: 0; padding: 0;">
        
        <!-- Outer Container -->
        <table border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color: #f4f6f8;">
            <tr>
                <td align="center" style="padding: 40px 0;">
                    
                    <!-- Main Card -->
                    <table border="0" cellpadding="0" cellspacing="0" width="600" style="background-color: #ffffff; border-radius: 10px; box-shadow: 0 4px 15px rgba(0,0,0,0.05); overflow: hidden; border: 1px solid #e1e4e8;">
                        
                        <!-- Header Branding -->
                        <tr>
                            <td align="center" style="background-color: {brand_color}; padding: 35px 0;">
                                <h2 style="color: #ffffff; margin: 0; font-size: 24px; font-weight: 700; letter-spacing: 0.5px;">
                                    {brand_name}
                                </h2>
                                <div style="height: 4px; width: 50px; background-color: #ffc107; margin: 10px auto 0; border-radius: 2px;"></div>
                            </td>
                        </tr>

                        <!-- Content Body -->
                        <tr>
                            <td style="padding: 40px 35px;">
                                
                                <p style="font-size: 18px; color: #333333; margin: 0 0 10px 0;">
                                    Hello <strong>{tenant_name}</strong>,
                                </p>
                                
                                <p style="font-size: 16px; color: #555555; line-height: 1.6; margin: 0 0 30px 0;">
                                    Thank you for choosing {brand_name}. We are processing your request, and we require a deposit to finalize your booking.
                                </p>

                                <!-- Amount Highlight Box -->
                                <table border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color: #f8f9fa; border-left: 5px solid {brand_color}; border-radius: 4px; margin-bottom: 30px;">
                                    <tr>
                                        <td style="padding: 20px;">
                                            <p style="margin: 0 0 5px 0; font-size: 13px; color: #888888; text-transform: uppercase; letter-spacing: 1px; font-weight: 600;">
                                                Deposit Amount
                                            </p>
                                            <p style="margin: 0; font-size: 32px; color: #333333; font-weight: 700;">
                                                KES {amount}
                                            </p>
                                        </td>
                                    </tr>
                                </table>

                                <p style="font-size: 16px; color: #555555; line-height: 1.6; margin: 0 0 30px 0;">
                                    Please click the button below to complete your secure payment via M-Pesa. This link is unique to your account and will expire shortly.
                                </p>

                                <!-- Primary CTA Button -->
                                <table border="0" cellpadding="0" cellspacing="0" width="100%">
                                    <tr>
                                        <td align="center">
                                            <a href="{payment_url}" target="_blank" style="background-color: #28a745; color: #ffffff; font-family: sans-serif; font-size: 16px; font-weight: bold; padding: 15px 35px; border-radius: 5px; text-decoration: none; display: inline-block; box-shadow: 0 4px 6px rgba(40, 167, 69, 0.2);">
                                                Pay Deposit Now
                                            </a>
                                        </td>
                                    </tr>
                                </table>
                                
                                <!-- Fallback Link -->
                                <p style="text-align: center; font-size: 13px; color: #888888; margin-top: 25px; line-height: 1.5;">
                                    Button not working? Paste this link into your browser:<br>
                                    <a href="{payment_url}" style="color: {brand_color}; word-break: break-all;">{payment_url}</a>
                                </p>

                            </td>
                        </tr>

                        <!-- Footer -->
                        <tr>
                            <td align="center" style="background-color: #f1f3f5; padding: 25px; border-top: 1px solid #e9ecef;">
                                <p style="margin: 0 0 10px 0; font-size: 13px; color: #6c757d;">
                                    Need help? Contact our support team.
                                </p>
                                <p style="margin: 0; font-size: 12px; color: #adb5bd;">
                                    &copy; {datetime.now().year} {brand_name}. All rights reserved.
                                </p>
                            </td>
                        </tr>

                    </table>
                    
                    <!-- Post-Script / Warning -->
                    <p style="text-align: center; font-size: 12px; color: #999999; margin-top: 20px; max-width: 500px; margin-left: auto; margin-right: auto;">
                        If you did not request this payment, please ignore this email or contact support immediately.
                    </p>

                </td>
            </tr>
        </table>
    </body>
    </html>
    """

    # Initialize the message payload for Mailjet v3.1
    sender_email = os.environ.get("SENDER_EMAIL", "noreply@homehub.app")
    sender_name = os.environ.get("SENDER_NAME", "HouseHub Kenya")

    data = {
        "Messages": [
            {
                "From": {"Email": sender_email, "Name": sender_name},
                "To": [{"Email": to_email, "Name": tenant_name}],
                "Subject": "Action Required: Deposit Payment Request",
                "HTMLPart": html_content,
                "TextPart": f"Please complete payment of KES {amount}: {payment_url}",
            }
        ]
    }

    try:
        # Initialize Mailjet SDK client
        mailjet = Client(auth=(os.environ.get("MAILJET_API_KEY"), os.environ.get("MAILJET_API_SECRET")), version="v3.1")

        # Send message
        result = mailjet.send.create(data=data)

        # Logging success
        status = getattr(result, "status_code", None)

        if status in [200, 201]:
            print("✅ EMAIL SENT SUCCESSFULLY")
        else:
            print("❌ EMAIL FAILED")
            print("📊 Status Code:", status)
            print("📩 Response:", result.json())
            raise Exception(f"Mailjet error: {status}")

        return result

    except Exception as e:
        # Detailed Error Logging
        import traceback, json
        print("❌ MAILJET ERROR OCCURRED:")
        traceback.print_exc()

        # Try to show response body if available
        try:
            body = getattr(e, 'response', None) or getattr(e, 'body', None)
            if body:
                try:
                    parsed = json.loads(body)
                    print("❌ MAILJET API DETAILS:", parsed)
                except Exception:
                    print("❌ MAILJET RESPONSE BODY:", body)
        except Exception:
            pass

        raise