import os
from flask import current_app, render_template, url_for
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

def generate_and_save_receipt(payment):
    """Render the payment receipt HTML and save to static/uploads/receipts.
    Returns the public URL to the saved receipt HTML file.
    """
    try:
        # Render HTML using template
        html = render_template('receipts/payment_receipt.html', payment=payment)

        # Determine output directory under app static folder
        app = current_app._get_current_object()
        static_dir = Path(app.static_folder) / 'uploads' / 'receipts'
        static_dir.mkdir(parents=True, exist_ok=True)

        filename = f"receipt-{payment.id}.html"
        out_path = static_dir / filename

        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(html)

        # Build public URL
        receipt_url = url_for('static', filename=f'uploads/receipts/{filename}', _external=True)

        # Persist receipt_url into payment if possible
        try:
            payment.receipt_url = receipt_url
            from extensions import db
            db.session.add(payment)
            db.session.commit()
        except Exception:
            logger.exception('Failed to save receipt_url to payment')

        return receipt_url
    except Exception:
        logger.exception('Failed to generate receipt')
        return None
