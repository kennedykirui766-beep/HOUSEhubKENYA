import os

class Config:
    # Secret key
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret")

    # Get database URL safely
    database_url = os.environ.get("DATABASE_URL")

    # Fix postgres:// issue (Render/Neon)
    if database_url and database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    # Final DB URI (never leave this as None)
    SQLALCHEMY_DATABASE_URI = database_url or os.environ.get("SQLITE_FALLBACK_URL", "sqlite:///app.db")

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Neon requires SSL
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }
    
    # ========== EMAIL CONFIGURATION ==========
    # Email provider: 'smtp', 'MAILJET', 'mailgun'
    # Default to Mailjet for this deployment
    EMAIL_PROVIDER = os.environ.get('EMAIL_PROVIDER', 'MAILJET')
    SENDER_EMAIL = os.environ.get('SENDER_EMAIL', 'noreply@homehub.app')
    SENDER_NAME = os.environ.get('SENDER_NAME', 'HOUSEhubKENYA')
    
    # SMTP Configuration (used if EMAIL_PROVIDER='smtp')
    MAIL_SERVER = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', True)
    MAIL_USE_SSL = os.environ.get('MAIL_USE_SSL', False)
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME', '')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD', '')
    
    # MAILJET API Key (if EMAIL_PROVIDER='MAILJET')
    MAILJET_API_KEY = os.environ.get('MAILJET_API_KEY', '')
    # MAILJET API Secret (used by SDK)
    MAILJET_API_SECRET = os.environ.get('MAILJET_API_SECRET', '')
    
    # Mailgun Configuration (if EMAIL_PROVIDER='mailgun')
    MAILGUN_DOMAIN = os.environ.get('MAILGUN_DOMAIN', '')
    MAILGUN_API_KEY = os.environ.get('MAILGUN_API_KEY', '')
    
    # ========== SMS CONFIGURATION (TWILIO) ==========
    TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID', '')
    TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN', '')
    TWILIO_FROM_NUMBER = os.environ.get('TWILIO_FROM_NUMBER', '')
    
    # ========== 2FA SETTINGS ==========
    OTP_CODE_LENGTH = 6  # 6-digit OTP
    OTP_TIMEOUT_SECONDS = 300  # 5 minutes
    MAX_OTP_ATTEMPTS = 5  # Max attempts before blocking
    BACKUP_CODES_COUNT = 10  # Number of backup codes generated

    # ========== ADMIN SECURITY ==========
    ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', '')
    ADMIN_RATE_LIMIT = int(os.environ.get('ADMIN_RATE_LIMIT', 20))
    ADMIN_RATE_LIMIT_WINDOW = int(os.environ.get('ADMIN_RATE_LIMIT_WINDOW', 60))
    # Comma-separated allowlist of IP/CIDR entries for admin pages.
    # Example: "127.0.0.1,10.0.0.0/8,41.90.12.33"
    ADMIN_IP_ALLOWLIST = os.environ.get('ADMIN_IP_ALLOWLIST', '')
    # Admin idle session timeout (seconds) - default 1 hour
    ADMIN_SESSION_TIMEOUT_SECONDS = int(os.environ.get('ADMIN_SESSION_TIMEOUT_SECONDS', 3600))
    
    # Upload folders
    UPLOAD_FOLDER = os.environ.get(
        "UPLOAD_FOLDER",
        os.path.join(os.getcwd(), "static/images")
    )

    # Official logo filename relative to `static/` (canonical: 'images/logo.png')
    APP_LOGO = os.environ.get('APP_LOGO', 'images/logo.png')

    CHAT_UPLOAD_FOLDER = os.environ.get(
        "CHAT_UPLOAD_FOLDER",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "static/uploads/chat")
    )

    # File limits
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "pdf"}
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5MB
    
    import cloudinary

    cloudinary.config(
        cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
        api_key=os.environ.get("CLOUDINARY_API_KEY"),
        api_secret=os.environ.get("CLOUDINARY_API_SECRET"),
        secure=True
    )
    