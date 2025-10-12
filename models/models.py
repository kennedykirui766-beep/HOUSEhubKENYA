from extensions import db
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    phone_number = db.Column(db.String(20), unique=True, nullable=True)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='tenant')
    two_factor_enabled = db.Column(db.Boolean, default=False)
    two_factor_secret = db.Column(db.String(32), nullable=True)
    mpesa_details = db.Column(db.String(50), nullable=True)
    profile_picture = db.Column(db.String(255), nullable=True)
    language = db.Column(db.String(10), default='en')

    # Relationships
    houses = db.relationship('House', backref='owner', lazy=True)
    bookings = db.relationship('Booking', backref='tenant', lazy=True)
    sent_messages = db.relationship(
        'Message',
        foreign_keys='Message.sender_id',
        backref='sender',
        lazy=True
    )
    received_messages = db.relationship(
        'Message',
        foreign_keys='Message.receiver_id',
        backref='receiver',
        lazy=True
    )
    payments = db.relationship('Payment', backref='tenant', lazy=True)
    maintenance_requests = db.relationship('MaintenanceRequest', backref='tenant', lazy=True)
    notifications = db.relationship('Notification', backref='tenant', lazy=True)
    events = db.relationship('Event', backref='tenant', lazy=True)

    # Chat relationships
    sent_chat_messages = db.relationship(
        'ChatMessage',
        foreign_keys='ChatMessage.user_id',
        back_populates='user',
        lazy=True,
        cascade="all, delete-orphan"
    )
    received_chat_messages = db.relationship(
        'ChatMessage',
        foreign_keys='ChatMessage.support_agent_id',
        back_populates='agent',
        lazy=True,
        cascade="all, delete-orphan"
    )

    # Support tickets
    support_tickets = db.relationship('SupportTicket', back_populates='user', lazy=True)

    # Password utils
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class House(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200))
    description = db.Column(db.Text)
    category = db.Column(db.String(50))
    image_urls = db.Column(db.Text)
    location = db.Column(db.String(255))
    lat = db.Column(db.Float)
    lng = db.Column(db.Float)
    available = db.Column(db.Boolean, default=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'))

    address_line1 = db.Column(db.String(255))
    address_line2 = db.Column(db.String(255))
    city = db.Column(db.String(100))
    state_province = db.Column(db.String(100))
    postal_code = db.Column(db.String(20))
    country = db.Column(db.String(100))

    rent_amount = db.Column(db.Float)
    property_type = db.Column(db.String(50))
    bedrooms = db.Column(db.Integer)
    bathrooms = db.Column(db.Float)
    size = db.Column(db.String(50))
    lease_term = db.Column(db.String(50))
    availability_date = db.Column(db.Date)

    utilities = db.Column(db.Text)
    pets_allowed = db.Column(db.String(10))
    pet_restrictions = db.Column(db.String(255))
    parking_availability = db.Column(db.String(50))
    furnished_status = db.Column(db.String(50))
    amenities = db.Column(db.Text)
    security_deposit = db.Column(db.Float)
    smoking_policy = db.Column(db.String(50))
    accessibility_features = db.Column(db.Text)
    

class ServiceRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    service_provider_id = db.Column(db.Integer, db.ForeignKey('service_provider.id'), nullable=False)
    description = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(50), default='Pending')
    amount = db.Column(db.Numeric(10, 2), nullable=True) 
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)
    date = db.Column(db.DateTime, nullable=False)  
    date_submitted = db.Column(db.DateTime, default=datetime.utcnow)

    tenant = db.relationship('User', foreign_keys=[tenant_id])
    service_provider = db.relationship('ServiceProvider', foreign_keys=[service_provider_id])




class Appointment(db.Model):
    __tablename__ = 'appointment'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    service_provider_id = db.Column(db.Integer, db.ForeignKey('service_provider.id'), nullable=False)
    scheduled_date = db.Column(db.DateTime, nullable=False)
    date = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(50), default="Scheduled")
    notes = db.Column(db.Text)

    tenant = db.relationship('User', backref='appointments')
    service_provider = db.relationship('ServiceProvider', backref='appointments')


class Review(db.Model):
    __tablename__ = 'review'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    service_provider_id = db.Column(db.Integer, db.ForeignKey('service_provider.id'), nullable=False)
    rating = db.Column(db.Integer, nullable=False)
    comment = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    tenant = db.relationship('User', backref='reviews')
    service_provider = db.relationship('ServiceProvider', backref='reviews')


class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    house_id = db.Column(db.Integer, db.ForeignKey('house.id'))
    status = db.Column(db.String(50))
    lease_start_date = db.Column(db.Date)
    lease_end_date = db.Column(db.Date)

class Document(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    content = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=db.func.current_timestamp())


class ServiceProvider(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    service = db.Column(db.String(200))
    phone = db.Column(db.String(20))
    description = db.Column(db.Text)
    service_type = db.Column(db.String(100))
    location = db.Column(db.String(255), default="Not specified")
    available = db.Column(db.Boolean, default=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))


class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    amount = db.Column(db.Float, nullable=False)
    date = db.Column(db.Date, nullable=False)
    due_date = db.Column(db.Date)
    status = db.Column(db.String(20), default='Pending')


class MaintenanceRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    issue = db.Column(db.String(200), nullable=False)
    status = db.Column(db.String(20), default='Open')
    date_submitted = db.Column(db.DateTime, default=db.func.current_timestamp())


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    message = db.Column(db.Text, nullable=False)
    date = db.Column(db.DateTime, default=db.func.current_timestamp())


class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    title = db.Column(db.String(100), nullable=False)
    date = db.Column(db.Date, nullable=False)


# ----------------- ChatMessage -----------------
class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    support_agent_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    message = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=db.func.current_timestamp())
    is_read = db.Column(db.Boolean, default=False)

    # Relationships (use back_populates to avoid conflicts)
    user = db.relationship('User', foreign_keys=[user_id], back_populates='sent_chat_messages')
    agent = db.relationship('User', foreign_keys=[support_agent_id], back_populates='received_chat_messages')


# ----------------- SupportTicket -----------------
class SupportTicket(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    subject = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(50), default='open')  # open, resolved, escalated
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())
    updated_at = db.Column(
        db.DateTime,
        default=db.func.current_timestamp(),
        onupdate=db.func.current_timestamp()
    )

    # Relationship
    user = db.relationship('User', back_populates='support_tickets')
