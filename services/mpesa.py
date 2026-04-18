import os
import requests
import base64
from datetime import datetime

from models.models import PaymentLink, db


def stk_push(phone, amount, link_id):
    consumer_key = os.environ.get("MPESA_CONSUMER_KEY")
    consumer_secret = os.environ.get("MPESA_CONSUMER_SECRET")
    shortcode = os.environ.get("MPESA_SHORTCODE")
    passkey = os.environ.get("MPESA_PASSKEY")

    # 🔐 Access token
    auth_url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
    response = requests.get(auth_url, auth=(consumer_key, consumer_secret))
    access_token = response.json().get("access_token")

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")

    password = base64.b64encode(
        (shortcode + passkey + timestamp).encode()
    ).decode("utf-8")

    stk_url = "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    callback_url = os.environ.get("MPESA_CALLBACK_URL")

    # 🔥 Get the EXACT payment link
    link = PaymentLink.query.get(link_id)

    if not link:
        print("❌ PaymentLink not found")
        return None

    # 🔥 Dynamic description (deposit vs featured)
    if link.payment_type == "featured":
        description = "Featured Property Payment"
        account_ref = f"FEATURED-{link.token}"
    else:
        description = "House Deposit Payment"
        account_ref = f"DEPOSIT-{link.token}"

    payload = {
        "BusinessShortCode": shortcode,
        "Password": password,
        "Timestamp": timestamp,
        "TransactionType": "CustomerPayBillOnline",
        "Amount": amount,
        "PartyA": phone,
        "PartyB": shortcode,
        "PhoneNumber": phone,
        "CallBackURL": callback_url,

        # 🔥 VERY IMPORTANT
        "AccountReference": account_ref,
        "TransactionDesc": description
    }

    response = requests.post(stk_url, json=payload, headers=headers)
    res_data = response.json()

    print("📦 STK RESPONSE:", res_data)

    checkout_request_id = res_data.get("CheckoutRequestID")

    # ✅ SAVE TO SAME ROW (FIXED)
    if checkout_request_id:
        link.checkout_request_id = checkout_request_id
        db.session.commit()
        print("✅ CheckoutRequestID saved:", checkout_request_id)

    return {
        "response": res_data,
        "checkout_request_id": checkout_request_id
    }