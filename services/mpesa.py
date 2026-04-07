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

    payload = {
        "BusinessShortCode": shortcode,
        "Password": password,
        "Timestamp": timestamp,
        "TransactionType": "CustomerPayBillOnline",
        "Amount": amount,
        "PartyA": phone,
        "PartyB": shortcode,
        "PhoneNumber": phone,
        # ✅ FIXED CALLBACK URL
        "CallBackURL": "https://yourdomain.com/payments/api/mpesa/callback",
        "AccountReference": "HouseHub",
        "TransactionDesc": "Payment"
    }

    response = requests.post(stk_url, json=payload, headers=headers)
    res_data = response.json()

    print("📦 STK RESPONSE:", res_data)  # ✅ DEBUG

    # ✅ Extract CheckoutRequestID for callback mapping
    checkout_request_id = res_data.get("CheckoutRequestID")

    return {
        "response": res_data,
        "checkout_request_id": checkout_request_id
    }


