from flask import Blueprint

payments_bp = Blueprint("payments", __name__, url_prefix="/payments")

from flask_login import login_required, current_user
from flask import render_template, request, redirect, url_for, flash
from models.models import PaymentLink, db
from extensions import db, csrf
from services.mpesa import stk_push

@csrf.exempt
@payments_bp.route("/pay/<string:token>", methods=["GET", "POST"])
def pay(token):
    # 🔍 Get payment link
    link = PaymentLink.query.filter_by(token=token).first_or_404()

    from datetime import datetime

    # ⏳ Check expiry
    if link.expires_at < datetime.utcnow():
        link.status = "expired"
        db.session.commit()

        flash("This payment link has expired.", "danger")
        return render_template("payments/expired.html", link=link)

    # 🚫 Prevent reuse
    if link.status == "paid":
        flash("This payment link has already been used.", "warning")
        return render_template("payments/already_paid.html", link=link)

    # 🧠 Optional: If user is logged in, verify ownership
    if current_user.is_authenticated:
        if link.tenant_id != current_user.id:
            flash("Unauthorized access to this payment link.", "danger")
            return redirect(url_for("tenant.dashboard"))

    if request.method == "POST":
        phone = request.form.get("phone")

        if not phone:
            flash("Phone number is required.", "danger")
            return redirect(request.url)

        # ✅ CLEAN + NORMALIZE PHONE NUMBER
        phone = phone.strip()

        # Remove spaces and plus sign
        phone = phone.replace(" ", "").replace("+", "")

        # 🔄 Convert formats to 254XXXXXXXXX (recommended for M-Pesa)
        if phone.startswith("0") and len(phone) == 10:
            phone = "254" + phone[1:]  # 07... → 2547...

        elif phone.startswith("7") and len(phone) == 9:
            phone = "254" + phone  # 7411... → 2547411...

        elif phone.startswith("254") and len(phone) == 12:
            pass  # already correct

        else:
            flash("Enter a valid phone number (e.g. 741117778, 0741117778, or 254741117778).", "danger")
            return redirect(request.url)

        try:
            # 💳 🚀 TRIGGER STK PUSH (ADDED — not replacing your logic)
            stk_response = stk_push(phone, link.amount)
            print("📲 STK RESPONSE:", stk_response)

            # ⚠️ IMPORTANT: Do NOT mark as paid yet
            # Payment will be confirmed via callback

            # 💰 Process payment (simulated)
            link.phone = phone
            link.transaction_id = f"TXN-{datetime.utcnow().timestamp()}"
            link.paid_at = datetime.utcnow()

            # ❗ We keep status pending until callback confirms
            link.status = "pending"

            # ❗ DO NOT approve booking here yet
            # if link.booking:
            #     link.booking.status = "approved"

            db.session.commit()

            flash("📲 STK Push sent. Enter your M-Pesa PIN to complete payment.", "success")

            return redirect(url_for("payments.pay", token=token))

        except Exception as e:
            db.session.rollback()
            flash("Payment failed. Try again.", "danger")

    return render_template("payments/pay.html", link=link)

@payments_bp.route("/api/mpesa/callback", methods=["POST"])
def mpesa_callback():
    from datetime import datetime

    data = request.get_json()
    print("📩 MPESA CALLBACK RECEIVED:", data)

    try:
        # ✅ SAFER ACCESS
        result = data.get("Body", {}).get("stkCallback", {})

        # 🧠 Extract important details
        merchant_request_id = result.get("MerchantRequestID")
        checkout_request_id = result.get("CheckoutRequestID")
        result_code = result.get("ResultCode")
        result_desc = result.get("ResultDesc")

        print("🔎 Result Code:", result_code)
        print("📝 Description:", result_desc)

        # ❗ Guard
        if not checkout_request_id:
            print("⚠️ Missing CheckoutRequestID")
            return {"ResultCode": 0, "ResultDesc": "Accepted"}

        # 🔍 Find payment link
        link = PaymentLink.query.filter_by(checkout_request_id=checkout_request_id).first()

        if not link:
            print("⚠️ Payment link not found for this callback")
            return {"ResultCode": 0, "ResultDesc": "Accepted"}

        # ✅ SUCCESSFUL PAYMENT
        if result_code == 0:
            print("✅ Payment successful")

            metadata = result.get("CallbackMetadata", {}).get("Item", [])

            # Extract transaction details
            amount = None
            mpesa_code = None
            phone = None

            for item in metadata:
                if item["Name"] == "Amount":
                    amount = item["Value"]
                elif item["Name"] == "MpesaReceiptNumber":
                    mpesa_code = item["Value"]
                elif item["Name"] == "PhoneNumber":
                    phone = item["Value"]

            # ✅ Update database
            link.status = "paid"
            link.transaction_id = mpesa_code
            link.phone = phone
            link.paid_at = datetime.utcnow()

            if link.booking:
                link.booking.status = "approved"

            db.session.commit()

            print("💾 Payment saved successfully")

        else:
            # ❌ FAILED PAYMENT
            print("❌ Payment failed")

            link.status = "failed"
            db.session.commit()

        return {"ResultCode": 0, "ResultDesc": "Accepted"}

    except Exception as e:
        import traceback
        print("❌ CALLBACK ERROR:")
        traceback.print_exc()

        return {"ResultCode": 0, "ResultDesc": "Accepted"}


@payments_bp.route("/success/<string:token>")
@login_required
def success(token):
    link = PaymentLink.query.filter_by(token=token).first_or_404()

    if link.booking.tenant_id != current_user.id:
        flash("Unauthorized access.", "danger")
        return redirect(url_for("tenant.dashboard"))

    return render_template("payments/success.html", link=link)