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
    #  Get payment link
    link = PaymentLink.query.filter_by(token=token).first_or_404()

    from datetime import datetime

    # ⏳ SAFE EXPIRY CHECK (FIXED)
    try:
        if not link.expires_at:
            flash("This payment link is invalid or missing expiry.", "danger")
            return render_template("payments/expired.html", link=link)

        if link.expires_at < datetime.utcnow():
            link.status = "expired"
            db.session.commit()

            flash("This payment link has expired.", "danger")
            return render_template("payments/expired.html", link=link)

    except Exception as e:
        print("Expiry check error:", e)
        flash("Error checking payment link expiry.", "danger")
        return render_template("payments/expired.html", link=link)

    # Prevent reuse
    if link.status == "paid":
        flash("This payment link has already been used.", "warning")
        return render_template("payments/already_paid.html", link=link)

    # ADD: Redirect if payment already failed
    if link.status == "failed":
        flash("Previous payment failed. Please try again.", "danger")
        return redirect(url_for("payments.failed", token=token))

    # Optional: If user is logged in, verify ownership
    if current_user.is_authenticated:
        if link.tenant_id != current_user.id:
            flash("Unauthorized access to this payment link.", "danger")
            return redirect(url_for("tenant.dashboard"))

    if request.method == "POST":
        phone = request.form.get("phone")

        if not phone:
            flash("Phone number is required.", "danger")
            return redirect(request.url)

        #  CLEAN + NORMALIZE PHONE NUMBER
        phone = phone.strip()

        # Remove spaces and plus sign
        phone = phone.replace(" ", "").replace("+", "")

        #  Convert formats to 254XXXXXXXXX
        if phone.startswith("0") and len(phone) == 10:
            phone = "254" + phone[1:]

        elif phone.startswith("7") and len(phone) == 9:
            phone = "254" + phone

        elif phone.startswith("254") and len(phone) == 12:
            pass

        else:
            flash("Enter a valid phone number (e.g. 741117778, 0741117778, or 254741117778).", "danger")
            return redirect(request.url)

        try:
            # TRIGGER STK PUSH
            stk_response = stk_push(phone, link.amount)
            print("📲 STK RESPONSE:", stk_response)

            # ✅ FIX: Proper extraction of CheckoutRequestID
            checkout_request_id = (
                stk_response.get("CheckoutRequestID") or
                stk_response.get("checkout_request_id") or
                (stk_response.get("response") or {}).get("CheckoutRequestID")
            )

            if not checkout_request_id:
                raise Exception("Missing CheckoutRequestID from STK response")

            # ✅ SAVE CheckoutRequestID FIRST
            link.checkout_request_id = checkout_request_id

            # Save details (DO NOT mark as paid)
            link.phone = phone
            link.transaction_id = f"TXN-{datetime.utcnow().timestamp()}"

            # ❌ REMOVE THIS (wrong to set before payment)
            # link.paid_at = datetime.utcnow()

            #  Set to pending (wait for callback)
            link.status = "pending"

            db.session.commit()

            flash("📲 STK Push sent. Enter your M-Pesa PIN to complete payment.", "success")

            return redirect(url_for("payments.pending", token=token))

        except Exception as e:
            print(" STK ERROR:", e)
            db.session.rollback()

            link.status = "failed"
            db.session.commit()

            flash("Payment failed. Try again.", "danger")

    # Final redirects
    if link.status == "paid":
        return redirect(url_for("payments.success", token=token))

    if link.status == "failed":
        return redirect(url_for("payments.failed", token=token))

    return render_template("payments/pay.html", link=link)

@csrf.exempt
@payments_bp.route("/api/mpesa/callback", methods=["POST"])
def mpesa_callback():
    from datetime import datetime

    data = request.get_json()
    print("MPESA CALLBACK RECEIVED:", data)

    try:
        # SAFER ACCESS
        result = data.get("Body", {}).get("stkCallback", {})

        # Extract important details
        merchant_request_id = result.get("MerchantRequestID")
        checkout_request_id = result.get("CheckoutRequestID")
        result_code = result.get("ResultCode")
        result_desc = result.get("ResultDesc")

        print("Result Code:", result_code)
        print("Description:", result_desc)

        # Guard
        if not checkout_request_id:
            print(" Missing CheckoutRequestID")
            return {"ResultCode": 0, "ResultDesc": "Accepted"}

        # Find payment link
        link = PaymentLink.query.filter_by(checkout_request_id=checkout_request_id).first()

        if not link:
            print("Payment link not found for this callback")
            return {"ResultCode": 0, "ResultDesc": "Accepted"}

        # =========================
        # SUCCESSFUL PAYMENT
        # =========================
        if result_code == 0:
            print("Payment successful")

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

            # Update database
            link.status = "paid"
            link.transaction_id = mpesa_code
            link.phone = phone
            link.paid_at = datetime.utcnow()

            # ✅ FIX: booking is NOT defined → safely handle only if it exists
            if hasattr(link, "booking") and link.booking:
                link.booking.status = "approved"

            db.session.commit()

            print("Payment saved successfully")

        # =========================
        # FAILED PAYMENT (NEW IMPROVEMENT)
        # =========================
        else:
            print("Payment failed")

            link.status = "failed"
            link.transaction_id = f"FAILED-{checkout_request_id}"

            # ✅ FIX: avoid crash if column doesn't exist yet
            if hasattr(link, "failure_reason"):
                link.failure_reason = result_desc

            db.session.commit()

        # =========================
        # EXTRA: HANDLE NO CALLBACK METADATA
        # =========================
        if result_code == 0 and not result.get("CallbackMetadata"):
            print("No metadata found in success callback")

        return {"ResultCode": 0, "ResultDesc": "Accepted"}
    


    except Exception as e:
        import traceback
        print(" CALLBACK ERROR:")
        traceback.print_exc()

        return {"ResultCode": 0, "ResultDesc": "Accepted"}


@payments_bp.route("/success/<string:token>")
def success(token):
    link = PaymentLink.query.filter_by(token=token).first_or_404()

    # 🔐 Allow both tenant and landlord
    if current_user.is_authenticated:
        if current_user.id not in [link.tenant_id, link.landlord_id]:
            flash("Unauthorized access.", "danger")
            return redirect(url_for("main.index"))

        # 🎯 Determine dashboard based on role
        if current_user.role == "tenant":
            dashboard_url = url_for("tenant.dashboard")
        elif current_user.role == "landlord":
            dashboard_url = url_for("landlord.dashboard")
        else:
            dashboard_url = url_for("main.index")
    else:
        dashboard_url = url_for("main.index")

    # 🌍 Convert time to East Africa Time (EAT)
    import pytz
    from datetime import timezone

    eat = pytz.timezone("Africa/Nairobi")

    created_at_eat = None
    if link.created_at:
        if link.created_at.tzinfo is None:
            created_at_utc = link.created_at.replace(tzinfo=timezone.utc)
        else:
            created_at_utc = link.created_at

        created_at_eat = created_at_utc.astimezone(eat)

    return render_template(
        "payments/success.html",
        link=link,
        created_at_eat=created_at_eat,
        dashboard_url=dashboard_url  # ✅ pass to template
    )
    
@payments_bp.route("/failed/<string:token>")
def failed(token):
    link = PaymentLink.query.filter_by(token=token).first_or_404()

    return render_template("payments/failed.html", link=link)

@payments_bp.route("/pending/<string:token>")
def pending(token):
    link = PaymentLink.query.filter_by(token=token).first_or_404()

    print("Current status:", link.status)  # 🔍 debug

    # ✅ If paid → go to success/already paid page
    if link.status == "paid":
        print("Redirecting to success page")
        return redirect(url_for("payments.already_paid", token=token))

    # ❌ If failed → go to failed page (YOU WERE MISSING THIS)
    elif link.status == "failed":
        print("Redirecting to failed page")
        return redirect(url_for("payments.failed", token=token))

    # ⏳ Still pending
    return render_template("payments/pending.html", link=link)

@payments_bp.route("/already-paid/<string:token>")
def already_paid(token):
    link = PaymentLink.query.filter_by(token=token).first_or_404()

    return render_template("payments/already_paid.html", link=link)