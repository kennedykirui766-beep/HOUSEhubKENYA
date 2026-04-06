from flask import Blueprint

payments_bp = Blueprint("payments", __name__, url_prefix="/payments")

from flask_login import login_required, current_user
from flask import render_template, request, redirect, url_for, flash
from models import PaymentLink, db

@payments_bp.route("/pay/<string:token>", methods=["GET", "POST"])
@login_required
def pay(token):
    # 🔍 Get payment link
    link = PaymentLink.query.filter_by(token=token).first_or_404()

    from datetime import datetime

    # ⏳ CHECK EXPIRY FIRST
    if link.expires_at < datetime.utcnow():
        link.status = "expired"
        db.session.commit()

        flash("This payment link has expired.", "danger")
        return render_template("payments/expired.html", link=link)

    # 🔐 Ensure this payment belongs to logged-in tenant
    if link.tenant_id != current_user.id:
        flash("Unauthorized access to this payment link.", "danger")
        return redirect(url_for("tenant.dashboard"))

    # 🚫 Prevent reuse
    if link.status == "paid":
        flash("This payment link has already been used.", "warning")
        return render_template("payments/already_paid.html", link=link)

    if request.method == "POST":
        phone = request.form.get("phone")

        if not phone:
            flash("Phone number is required.", "danger")
            return redirect(request.url)

        try:
            # 💰 Simulated payment
            link.phone = phone
            link.status = "paid"
            link.transaction_id = f"TXN-{datetime.utcnow().timestamp()}"
            link.paid_at = datetime.utcnow()

            # ✅ Update booking
            if link.booking:
                link.booking.status = "approved"

            db.session.commit()

            flash("Payment successful!", "success")
            return redirect(url_for("payments.success", token=token))

        except Exception as e:
            db.session.rollback()
            flash("Payment failed. Try again.", "danger")

    return render_template("payments/pay.html", link=link)


@payments_bp.route("/success/<string:token>")
@login_required
def success(token):
    link = PaymentLink.query.filter_by(token=token).first_or_404()

    if link.booking.tenant_id != current_user.id:
        flash("Unauthorized access.", "danger")
        return redirect(url_for("tenant.dashboard"))

    return render_template("payments/success.html", link=link)