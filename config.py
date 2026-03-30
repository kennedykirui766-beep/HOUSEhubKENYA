# config.py
import os

class Config:
    # Secret key for Flask
    import os

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret")

    database_url = os.environ.get("DATABASE_URL")

    # Fix for PostgreSQL on Render
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    SQLALCHEMY_DATABASE_URI = database_url

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    UPLOAD_FOLDER = os.environ.get(
        "UPLOAD_FOLDER",
        os.path.join(os.getcwd(), "static/images")
    )

    CHAT_UPLOAD_FOLDER = os.environ.get(
        "CHAT_UPLOAD_FOLDER",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "static/images")
    )

    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "pdf"}
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024

    # Allowed file types
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "pdf"}
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5 MB
