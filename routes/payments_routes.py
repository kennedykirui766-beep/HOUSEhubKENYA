from flask import Blueprint

payments_bp = Blueprint("payments", __name__, url_prefix="/payments")

from flask_login import login_required, current_user
from flask import render_template, request, redirect, url_for, flash
from models.models import Booking, House, Payment, PaymentLink, db
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

            # -------------------------
            # UPDATE PAYMENT LINK
            # -------------------------
            link.status = "paid"
            link.transaction_id = mpesa_code
            link.phone = phone
            link.paid_at = datetime.utcnow()

            # =========================
            # EXISTING LOGIC (KEEP)
            # =========================
            if hasattr(link, "booking") and link.booking:
                link.booking.status = "approved"

            # =========================
            # 🔥 FORCE booking_id LOGIC (NEW FIX)
            # =========================
            booking = None
            house = None

            try:
                print("DEBUG booking_id:", getattr(link, "booking_id", None))
                print("DEBUG house_id:", getattr(link, "house_id", None))

                # ALWAYS fetch booking using booking_id
                if hasattr(link, "booking_id") and link.booking_id:
                    booking = Booking.query.get(link.booking_id)

                # Fetch house
                if hasattr(link, "house_id") and link.house_id:
                    house = House.query.get(link.house_id)

                if booking:
                    print(f"Booking found: {booking.id}")
                    booking.status = "approved"   # 🔥 FORCE UPDATE
                else:
                    print("Booking NOT FOUND")

                if booking and house:
                    print("Booking & House found")

                    # Prevent double allocation
                    if hasattr(house, "is_occupied") and not house.is_occupied:

                        # Only assign if deposit
                        if hasattr(link, "payment_type"):
                            is_deposit = link.payment_type == "deposit"
                        else:
                            is_deposit = True  # fallback

                        if is_deposit:
                            print("Processing deposit ownership...")

                            if hasattr(house, "is_occupied"):
                                house.is_occupied = True

                            if hasattr(house, "available"):
                                house.available = False

                            if hasattr(house, "tenant_id"):
                                house.tenant_id = booking.tenant_id

                            print("House successfully assigned to tenant")

                        else:
                            print("This is rent payment, not deposit")

                    else:
                        print("House already occupied")

                else:
                    print("Booking or House missing, skipping ownership logic")

            except Exception as inner_error:
                print("Ownership logic failed:", inner_error)
                
            # =========================
            # 🌟 FEATURED PROPERTY LOGIC (NEW - SAFE ADD)
            # =========================
            try:
                if hasattr(link, "payment_type") and link.payment_type == "featured":
                    print("Processing FEATURED property payment...")

                    # Ensure house exists
                    if not house and hasattr(link, "house_id") and link.house_id:
                        house = House.query.get(link.house_id)

                    if house:
                        from datetime import timedelta

                        # Mark as featured
                        house.is_featured = True
                        house.featured_until = datetime.utcnow() + timedelta(days=7)

                        print(f"✅ House {house.id} is now FEATURED until {house.featured_until}")
                    else:
                        print("⚠️ Featured payment but house not found")

            except Exception as feature_error:
                print("❌ Featured logic failed:", feature_error)

            # =========================
            # OPTIONAL: SAVE PAYMENT RECORD
            # =========================
            try:
                payment = Payment(
                    tenant_id=booking.tenant_id if booking else None,
                    amount=amount if amount else link.amount,
                    date=datetime.utcnow().date(),
                    status="Completed"
                )

                if hasattr(payment, "house_id") and house:
                    payment.house_id = house.id

                if hasattr(payment, "payment_month"):
                    payment.payment_month = None  # deposit

                db.session.add(payment)

            except Exception as pay_error:
                print("Payment save skipped:", pay_error)

            db.session.commit()

            print("Payment saved successfully")

        # =========================
        # FAILED PAYMENT
        # =========================
        else:
            print("Payment failed")

            link.status = "failed"
            link.transaction_id = f"FAILED-{checkout_request_id}"

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