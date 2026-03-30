import os

class Config:
    # Secret key
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret")

    # Get database URL safely
    database_url = os.environ.get("DATABASE_URL")

    # Fix postgres:// issue (Render/Neon)
    if database_url and database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    # Final DB URI
    SQLALCHEMY_DATABASE_URI = database_url

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Neon requires SSL
    SQLALCHEMY_ENGINE_OPTIONS = {
        "connect_args": {"sslmode": "require"}
    }

    # Upload folders
    UPLOAD_FOLDER = os.environ.get(
        "UPLOAD_FOLDER",
        os.path.join(os.getcwd(), "static/images")
    )

    CHAT_UPLOAD_FOLDER = os.environ.get(
        "CHAT_UPLOAD_FOLDER",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "static/uploads/chat")
    )

    # File limits
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "pdf"}
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5MB