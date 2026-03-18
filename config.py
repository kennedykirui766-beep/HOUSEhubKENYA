# config.py
import os

class Config:
    # Secret key for Flask
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret")  # fallback for local dev

    # PostgreSQL connection via DATABASE_URL (Render provides this)
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///app.db")

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Upload folders
    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", os.path.join(os.getcwd(), "static/images"))
    CHAT_UPLOAD_FOLDER = os.environ.get("CHAT_UPLOAD_FOLDER", os.path.join(os.getcwd(), "static/uploads/chat"))

    # Allowed file types
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "pdf"}
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5 MB

    # Debug prints (optional)
    print("Using DB URI:", SQLALCHEMY_DATABASE_URI)
    print("UPLOAD_FOLDER:", UPLOAD_FOLDER)
    print("CHAT_UPLOAD_FOLDER:", CHAT_UPLOAD_FOLDER)