from flask import Blueprint, render_template, abort, request, redirect, url_for
from flask_login import login_required, current_user
from models.models import House, Booking, User
from extensions import db, csrf

house_bp = Blueprint('house', __name__, url_prefix='/houses')

@house_bp.route('/rentals')
def rentals():
    houses = House.query.filter_by(category='Rental').all()
    return render_template('rentals.html', houses=houses)


@house_bp.route('/bnb')
def bnb():
    houses = House.query.filter_by(category='BNB').all()
    return render_template('bnb.html', houses=houses)

@house_bp.route('/real_estates')
def real_estates():
    houses = House.query.filter_by(category='RealEstate').all()
    return render_template('real_estates.html', houses=houses)

@house_bp.route('/')
def index():
    houses = House.query.all()  # Adjust query as needed
    print("Houses data:", houses)  # Debug output
    return render_template('index.html', houses=houses)

import json

@house_bp.route('/view/<int:property_id>')
@login_required
def view_property(property_id):
    """
    View details of a specific property (available or rented).
    """

    # Fetch house
    house = House.query.get_or_404(property_id)

    # Fetch owner
    owner = house.owner

    # Handle Cloudinary images properly
    image_list = []

    if house.image_urls:
        try:
            # Case 1: JSON list (recommended)
            image_list = json.loads(house.image_urls)

            # Ensure it's actually a list
            if not isinstance(image_list, list):
                image_list = []

        except Exception:
            # Case 2: Comma-separated fallback
            image_list = [
                img.strip() for img in house.image_urls.split(",")
                if img.strip()
            ]

    # ✅ Optimize Cloudinary images (faster loading)
    def optimize_cloudinary(url):
        if "res.cloudinary.com" in url:
            return url.replace("/upload/", "/upload/f_auto,q_auto/")
        return url

    image_list = [optimize_cloudinary(img) for img in image_list]

    # Determine status
    status = "Available" if house.available else "Rented"

    return render_template(
        'view_property.html',
        house=house,
        owner=owner,
        images=image_list,
        status=status
    )
@house_bp.route('/edit/<int:property_id>')
@login_required
def edit_property(property_id):
    """
    Edit details of a specific property.
    """
    property = House.query.get_or_404(property_id)
    if property.owner_id != current_user.id:
        abort(403)  # Forbidden if not the owner
    return render_template('edit_property.html', property=property)

@csrf.exempt
@house_bp.route('/request_rental/<int:property_id>', methods=['POST'])
@login_required
def request_rental(property_id):
    """
    Handle rental request from a tenant for a specific property and fetch tenant data.
    """
    if current_user.role.lower() != 'tenant':
        abort(403)  # Forbidden if not a tenant

    # Get the house
    house = House.query.get_or_404(property_id)

    # Create booking
    booking = Booking(
        tenant_id=current_user.id,
        house_id=property_id,
        status='pending'
    )

    db.session.add(booking)
    db.session.commit()

    # Fetch full tenant details
    tenant = User.query.get(current_user.id)

    tenant_data = {
        "id": tenant.id,
        "name": tenant.name,
        "email": tenant.email,
        "phone": tenant.phone,
        "role": tenant.role,
    }

    # You can now use tenant_data (e.g., send notification, log, etc.)
    print("Tenant Booking Info:", tenant_data)

    return redirect(url_for('tenant.dashboard'))