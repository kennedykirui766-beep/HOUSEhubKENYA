from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_wtf import CSRFProtect
from flask_socketio import SocketIO   # 👈 add this

# Database
db = SQLAlchemy()

# Migrations
migrate = Migrate()

# Authentication
login_manager = LoginManager()
login_manager.login_view = 'auth.login'  # 👈 should be endpoint, not template filename

# CSRF protection
csrf = CSRFProtect()

# WebSockets (real-time)
socketio = SocketIO(cors_allowed_origins="*")  # 👈 now available everywhere
