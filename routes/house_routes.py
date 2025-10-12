from flask import Blueprint, render_template, abort, request, redirect, url_for
from flask_login import login_required, current_user
from models.models import House, Booking
from extensions import db

house_bp = Blueprint('house', __name__, url_prefix='/houses')

@house_bp.route('/rentals')
def rentals():
    houses = House.query.filter_by(category='Rental').all()
    return render_template('rentals.html', houses=houses)

@house_bp.route('/hotels')
def hotels():
    houses = House.query.filter_by(category='Hotel').all()
    return render_template('hotel.html', houses=houses)

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

@house_bp.route('/view/<int:property_id>')
@login_required
def view_property(property_id):
    """
    View details of a specific property.
    """
    property = House.query.get_or_404(property_id)
    return render_template('view_property.html', property=property)

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

@house_bp.route('/request_rental/<int:property_id>', methods=['POST'])
@login_required
def request_rental(property_id):
    """
    Handle rental request from a tenant for a specific property.
    """
    if current_user.role.lower() != 'tenant':
        abort(403)  # Forbidden if not a tenant
    house = House.query.get_or_404(property_id)
    if house:
        booking = Booking(tenant_id=current_user.id, house_id=property_id, status='pending')
        db.session.add(booking)
        db.session.commit()
        return redirect(url_for('tenant.dashboard'))
    return "Property not found", 404