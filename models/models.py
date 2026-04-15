from extensions import db
from flask_login import UserMixin
from sqlalchemy import event, func, select
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import secrets
import string


def generate_public_id(length=10):
    charset = string.ascii_letters + string.digits
    return ''.join(secrets.choice(charset) for _ in range(length))


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(32), unique=True, nullable=True, index=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    phone_number = db.Column(db.String(20), unique=True, nullable=True)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='tenant')
    
    # -------------------------
    # 🏠 BUSINESS INFO (OPTIONAL)
    # -------------------------
    business_name = db.Column(db.String(255), nullable=True)
    bio = db.Column(db.Text, nullable=True)
    address = db.Column(db.String(255), nullable=True)

    # -------------------------
    # 🔔 PREFERENCES (OPTIONAL WITH DEFAULTS)
    # -------------------------
    email_notifications = db.Column(db.Boolean, nullable=True, default=True)
    message_alerts = db.Column(db.Boolean, nullable=True, default=True)

    # -------------------------
    # 🔐 2FA OPTIONS (OPTIONAL)
    # -------------------------
    sms_2fa_enabled = db.Column(db.Boolean, nullable=True, default=False)
    email_2fa_enabled = db.Column(db.Boolean, nullable=True, default=False)
    
    # Legacy 2FA (TOTP/QR based)
    two_factor_enabled = db.Column(db.Boolean, default=False)
    two_factor_secret = db.Column(db.String(32), nullable=True)
    
    # NEW: Preferred 2FA method when multiple are enabled
    preferred_2fa_method = db.Column(db.String(20), nullable=True)  # 'email', 'sms', 'totp'
    
    mpesa_details = db.Column(db.String(50), nullable=True)
    profile_picture = db.Column(db.String(255), nullable=True)
    language = db.Column(db.String(10), default='en')
    dashboard_order = db.Column(db.Text, nullable=True)

    # Relationships
    houses = db.relationship('House', backref='owner', lazy=True)
    bookings = db.relationship('Booking', back_populates='tenant', lazy=True)
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
    maintenance_requests = db.relationship('MaintenanceRequest',back_populates='tenant',lazy=True)
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


# --- Role & Permission models (new) ---
user_roles = db.Table(
    'user_roles',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('role_id', db.Integer, db.ForeignKey('role.id'), primary_key=True)
)

role_permissions = db.Table(
    'role_permissions',
    db.Column('role_id', db.Integer, db.ForeignKey('role.id'), primary_key=True),
    db.Column('permission_id', db.Integer, db.ForeignKey('permission.id'), primary_key=True)
)


class Role(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.String(255), nullable=True)

    permissions = db.relationship('Permission', secondary=role_permissions, backref='roles')

    def __repr__(self):
        return f"<Role {self.name}>"


class Permission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.String(255), nullable=True)

    def __repr__(self):
        return f"<Permission {self.name}>"


# Add relationship to User (preserve legacy `role` string for compatibility)
User.roles = db.relationship('Role', secondary=user_roles, backref='users')


@event.listens_for(User, 'before_insert')
def assign_public_id(mapper, connection, target):
    if target.public_id:
        return

    # Keep 10 as minimum, then add one character per additional 100M users.
    user_count = connection.execute(select(func.count(User.id))).scalar() or 0
    public_id_length = 10 + (user_count // 100000000)

    while True:
        candidate = generate_public_id(public_id_length)
        exists = connection.execute(
            select(User.id).where(User.public_id == candidate)
        ).first()
        if not exists:
            target.public_id = candidate
            break


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

    tenant_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    house_id = db.Column(db.Integer, db.ForeignKey('house.id'), nullable=False)

    status = db.Column(db.String(50), default="pending")  # pending, approved, rejected

    lease_start_date = db.Column(db.Date, nullable=True)
    lease_end_date = db.Column(db.Date, nullable=True)

    created_at = db.Column(db.DateTime, default=db.func.now())

    # Relationships (VERY useful)
    tenant = db.relationship('User', back_populates='bookings')
    house = db.relationship("House", backref="bookings")

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
    is_read = db.Column(db.Boolean, default=False)


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
    house_id = db.Column(db.Integer, db.ForeignKey('house.id'))  # ✅ ADD THIS

    amount = db.Column(db.Float, nullable=False)
    payment_month = db.Column(db.String(20), nullable=False)  # ✅ ADD THIS

    date = db.Column(db.Date, nullable=False)
    due_date = db.Column(db.Date)

    status = db.Column(db.String(20), default='Pending')


class MaintenanceRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    tenant_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    house_id = db.Column(db.Integer, db.ForeignKey('house.id'))
    description = db.Column(db.Text, nullable=False)
    issue = db.Column(db.String(200), nullable=False)
    status = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    date_submitted = db.Column(db.DateTime, default=db.func.current_timestamp())

    # Relationships (optional but powerful)
    tenant = db.relationship('User', back_populates='maintenance_requests')


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
    

class SupportMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    full_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20))

    role = db.Column(db.String(50))
    message = db.Column(db.Text, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Optional: link to user if logged in
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)


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


# ========== 2FA MODELS (NEW) ==========

class TwoFactorCode(db.Model):
    """
    Stores temporary verification codes for email/SMS 2FA.
    Codes expire after OTP_TIMEOUT_SECONDS.
    """
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    code = db.Column(db.String(6), nullable=False)  # 6-digit OTP
    method = db.Column(db.String(20), nullable=False)  # 'email' or 'sms'
    is_used = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
    
    user = db.relationship('User', backref='two_factor_codes')
    
    def is_expired(self):
        return datetime.utcnow() > self.expires_at
    
    def is_valid(self):
        return not self.is_used and not self.is_expired()


class TwoFactorVerification(db.Model):
    """
    Tracks which 2FA methods are enabled for each user.
    User can have multiple methods enabled (email, SMS, TOTP).
    """
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, unique=True, index=True)
    email_enabled = db.Column(db.Boolean, default=False)
    sms_enabled = db.Column(db.Boolean, default=False)
    totp_enabled = db.Column(db.Boolean, default=False)  # Existing QR code method
    
    # Track verified phone number for SMS (if different from user.phone_number)
    verified_phone = db.Column(db.String(20), nullable=True)
    phone_verified = db.Column(db.Boolean, default=False)
    
    # Backup codes (comma-separated, generated when 2FA enabled)
    backup_codes = db.Column(db.Text, nullable=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    user = db.relationship('User', backref='two_factor_verification', uselist=False)
    
    def get_backup_codes(self):
        """Return list of unused backup codes"""
        if not self.backup_codes:
            return []
        codes = self.backup_codes.split(',')
        return [c.strip() for c in codes if c.strip()]
    
    def use_backup_code(self, code):
        """Use a backup code and remove it from the list"""
        codes = self.get_backup_codes()
        if code in codes:
            codes.remove(code)
            self.backup_codes = ','.join(codes)
            return True
        return False
    
    def is_any_method_enabled(self):
        """Check if any 2FA method is enabled"""
        return self.email_enabled or self.sms_enabled or self.totp_enabled


class Subscriber(db.Model):
    """Stores newsletter/system update subscribers."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class SystemUpdateSubscriber(db.Model):
    """Stores system-update subscribers and their selected newsletter topics."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    topics = db.Column(db.Text, nullable=False, default='')  # comma-separated topic keys
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class SystemSetting(db.Model):
    """Simple key/value store for platform settings, including maintenance mode."""
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False, index=True)
    value = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    @staticmethod
    def get(key, default=None):
        try:
            s = SystemSetting.query.filter_by(key=key).first()
            return s.value if s else default
        except Exception:
            # If the table doesn't exist or DB is in an error state, rollback and return default
            try:
                db.session.rollback()
            except Exception:
                pass
            return default

    @staticmethod
    def set(key, value):
        try:
            s = SystemSetting.query.filter_by(key=key).first()
            if not s:
                s = SystemSetting(key=key, value=value)
                db.session.add(s)
            else:
                s.value = value
            db.session.commit()
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
            raise
        

class PaymentLink(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    token = db.Column(db.String(100), unique=True, nullable=False)

    landlord_id = db.Column(db.Integer, nullable=False)
    tenant_id = db.Column(db.Integer, nullable=True)  # ✅ ADD THIS
    booking_id = db.Column(db.Integer, nullable=False)
    house_id = db.Column(db.Integer, nullable=False)

    amount = db.Column(db.Float, nullable=False)

    status = db.Column(db.String(20), default="pending")  
    # pending, paid, expired

    phone = db.Column(db.String(20))  # who paid

    transaction_id = db.Column(db.String(100))  # M-Pesa receipt

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    checkout_request_id = db.Column(db.String(100), nullable=True)

    # ⏳ NEW: expiry
    expires_at = db.Column(
        db.DateTime,
        default=lambda: datetime.utcnow() + timedelta(hours=24)
    )

    paid_at = db.Column(db.DateTime)

    # 🔍 Optional: helper property
    @property
    def is_expired(self):
        return datetime.utcnow() > self.expires_at