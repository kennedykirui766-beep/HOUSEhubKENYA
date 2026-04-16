import os
import requests
import base64
from datetime import datetime

from flask import request  # ✅ ADDED
from models.models import PaymentLink, db  # ✅ ADDED db



def stk_push(phone, amount):
    consumer_key = os.environ.get("MPESA_CONSUMER_KEY")
    consumer_secret = os.environ.get("MPESA_CONSUMER_SECRET")
    shortcode = os.environ.get("MPESA_SHORTCODE")
    passkey = os.environ.get("MPESA_PASSKEY")

    # 🔐 Get access token
    auth_url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
    response = requests.get(auth_url, auth=(consumer_key, consumer_secret))
    access_token = response.json().get("access_token")

    # ⏱️ Timestamp
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")

    # 🔑 Password
    data_to_encode = shortcode + passkey + timestamp
    password = base64.b64encode(data_to_encode.encode()).decode('utf-8')

    stk_url = "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    # ✅ USE ENV VARIABLE (FIX)
    callback_url = os.environ.get("MPESA_CALLBACK_URL")

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
        "AccountReference": "HouseHub",
        "TransactionDesc": "Payment"
    }

    response = requests.post(stk_url, json=payload, headers=headers)
    res_data = response.json()

    print("📦 STK RESPONSE:", res_data)

    # ✅ Extract CheckoutRequestID
    checkout_request_id = res_data.get("CheckoutRequestID")

    # 🚨 IMPORTANT FIX: SAVE TO DATABASE
    if checkout_request_id:
        link = PaymentLink.query.filter_by(phone=phone).order_by(PaymentLink.id.desc()).first()

        if link:
            link.checkout_request_id = checkout_request_id
            db.session.commit()
            print("✅ CheckoutRequestID saved:", checkout_request_id)

    return {
        "response": res_data,
        "checkout_request_id": checkout_request_id
    }


def create_payment_link(amount, phone_number=None, account_ref=None):
    """Wrapper that attempts STK push and returns (link, transaction_id).
    Falls back to a dev URL when MPESA not configured.
    """
    try:
        res = stk_push(phone_number, amount)
        cid = res.get('checkout_request_id')
        if cid:
            link = f"mpesa://stk/{cid}"
            return link, cid
    except Exception:
        pass

    # fallback dev link
    tx = f"dev-{int(datetime.now().timestamp())}"
    link = f"https://example.com/pay/{tx}?amount={int(amount)}"
    return link, tx

