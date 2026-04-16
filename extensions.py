from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_wtf import CSRFProtect
from flask_socketio import SocketIO   # 👈 add this
from flask_mail import Mail
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import current_user



# Database
db = SQLAlchemy()

# Migrations
migrate = Migrate()

# Authentication
login_manager = LoginManager()
login_manager.login_view = 'auth.login'  # 👈 should be endpoint, not template filename

# CSRF protection
csrf = CSRFProtect()

mail = Mail()

# WebSockets (real-time)
socketio = SocketIO(cors_allowed_origins="*")  # 👈 now available everywhere
# Rate limiter configured to key by authenticated user id when available,
# otherwise fall back to remote address. Default limits left empty here;
# apply per-route limits via decorators.
def _limiter_key():
	try:
		if current_user and getattr(current_user, 'is_authenticated', False):
			return f"user:{getattr(current_user, 'id', 'anon')}"
	except Exception:
		pass
	return get_remote_address()

limiter = Limiter(key_func=_limiter_key, headers_enabled=True)
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_wtf import CSRFProtect
from flask_mail import Mail

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()
mail = Mail()

socketio = SocketIO(cors_allowed_origins="*")