import os

from dotenv import load_dotenv
import flask
from flask_migrate import upgrade

load_dotenv()

if os.environ.get("USE_EVENTLET") == "true":
    import eventlet
    eventlet.monkey_patch()

from flask import Flask, redirect, url_for, flash, render_template, request, session
from config import Config

# ✅ FIX: import socketio from extensions ONLY (single source of truth)
from extensions import db, migrate, login_manager, csrf, mail, socketio

from flask_cors import CORS
from models.models import User, House, ChatMessage, SupportTicket, SystemSetting
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError
from datetime import datetime
import logging

from utils_security import is_approved_admin


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Ensure critical configurations are set
    app.config['SQLALCHEMY_DATABASE_URI'] = (
        app.config.get('SQLALCHEMY_DATABASE_URI')
        or os.environ.get('DATABASE_URL')
        or 'sqlite:///app.db'
    )
    app.config['UPLOAD_FOLDER'] = app.config.get('UPLOAD_FOLDER', 'static/images')
    app.config['CHAT_UPLOAD_FOLDER'] = app.config.get('CHAT_UPLOAD_FOLDER', 'static/uploads/chat')
    app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif', 'pdf'}
    app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Setup logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    print("Final DB URI =", app.config['SQLALCHEMY_DATABASE_URI'])
    print("UPLOAD_FOLDER =", app.config['UPLOAD_FOLDER'])
    print("CHAT_UPLOAD_FOLDER =", app.config['CHAT_UPLOAD_FOLDER'])

    # Create upload folder
    os.makedirs(app.config['CHAT_UPLOAD_FOLDER'], exist_ok=True)

    # =========================
    # INIT EXTENSIONS (FIXED)
    # =========================
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    mail.init_app(app)
    socketio.init_app(app, cors_allowed_origins="*")  # ✅ FIXED HERE

    CORS(app)

    # CSRF exempt (your existing logic)
    csrf.exempt('routes.support_routes.support_bp')

    # =========================
    # LOGIN MANAGER
    # =========================
    @login_manager.user_loader
    def load_user(user_id):
        try:
            return User.query.get(int(user_id))
        except Exception as e:
            logger.error(f"Error loading user {user_id}: {str(e)}")
            return None

    # =========================
    # JINJA FILTERS (UNCHANGED)
    # =========================
    def timeago(value):
        if not isinstance(value, datetime):
            return value

        lang = getattr(current_user, "language", "en") if current_user.is_authenticated else "en"
        now = datetime.utcnow()
        diff = now - value

        seconds = diff.total_seconds()
        minutes = divmod(seconds, 60)[0]
        hours = divmod(seconds, 3600)[0]
        days = divmod(seconds, 86400)[0]

        if lang == "sw":
            if seconds < 60:
                return "sasa hivi"
            elif minutes < 60:
                return f"dakika {int(minutes)} zilizopita"
            elif hours < 24:
                return f"masaa {int(hours)} yaliyopita"
            elif days == 1:
                return "jana"
            elif days < 7:
                return f"siku {int(days)} zilizopita"
            elif days < 30:
                return f"wiki {int(days // 7)} zilizopita"
            elif days < 365:
                return f"miezi {int(days // 30)} iliyopita"
            else:
                return f"miaka {int(days // 365)} iliyopita"
        else:
            if seconds < 60:
                return "just now"
            elif minutes < 60:
                return f"{int(minutes)} minute(s) ago"
            elif hours < 24:
                return f"{int(hours)} hour(s) ago"
            elif days == 1:
                return "yesterday"
            elif days < 7:
                return f"{int(days)} day(s) ago"
            elif days < 30:
                return f"{int(days // 7)} week(s) ago"
            elif days < 365:
                return f"{int(days // 30)} month(s) ago"
            else:
                return f"{int(days // 365)} year(s) ago"

    def datetimeformat(value, format="%Y-%m-%d %H:%M"):
        if not isinstance(value, datetime):
            return value
        return value.strftime(format)

    app.jinja_env.filters['timeago'] = timeago
    app.jinja_env.filters['datetimeformat'] = datetimeformat

    # =========================
    # CONTEXT PROCESSOR
    # =========================
    @app.context_processor
    def inject_app_settings():
        try:
            from flask import url_for
            logo = app.config.get('APP_LOGO', 'images/homehub.jpg')

            if isinstance(logo, str) and (
                logo.startswith('http://')
                or logo.startswith('https://')
                or logo.startswith('//')
            ):
                logo_url = logo
            else:
                logo_url = url_for('static', filename=logo)

        except Exception:
            logo_url = '/static/images/homehub.jpg'

        return dict(APP_LOGO=logo, APP_LOGO_URL=logo_url)

    # =========================
    # BLUEPRINTS
    # =========================
    from routes.auth_routes import auth_bp
    from routes.landlord_routes import landlord_bp
    from routes.tenant_routes import tenant_bp
    from routes.admin_routes import admin_bp
    from routes.service_routes import service_provider_bp
    from routes.house_routes import house_bp
    from routes.main import main_bp
    from routes.support_routes import support_bp
    from routes.payments_routes import payments_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(landlord_bp)
    app.register_blueprint(tenant_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(service_provider_bp)
    app.register_blueprint(house_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(support_bp)
    app.register_blueprint(payments_bp)

    # =========================
    # ROUTES (UNCHANGED)
    # =========================
    @app.route('/')
    def root():
        logger.info("Redirecting to index page")
        return render_template('index.html')

    @app.route("/index")
    def index():
        try:
            houses = House.query.all()
            return render_template("index.html", houses=houses)
        except Exception as e:
            logger.error(f"Error fetching houses: {str(e)}")
            flash("Error loading houses. Please try again.", "danger")
            return render_template("index.html", houses=[])

    @app.route('/favicon.ico')
    def favicon():
        logo = app.config.get('APP_LOGO', 'images/logo.png')

        if isinstance(logo, str) and (
            logo.startswith('http://')
            or logo.startswith('https://')
            or logo.startswith('//')
        ):
            return redirect(logo)

        try:
            return app.send_static_file(logo)
        except Exception:
            return app.send_static_file('images/logo.png')

    @app.teardown_appcontext
    def shutdown_session(exception=None):
        if exception:
            db.session.rollback()
        db.session.remove()

    @app.route('/portal')
    @login_required
    def portal():
        role = current_user.role.lower()
        logger.info(f"User {current_user.id} accessing portal with role: {role}")

        if role == 'admin':
            if not is_approved_admin(current_user):
                flash("Access denied. Admins only.", "danger")
                return redirect(url_for('auth.logout'))
            return redirect(url_for('admin.manage_users'))

        elif role == 'landlord':
            return redirect(url_for('landlord.dashboard'))

        elif role == 'tenant':
            return redirect(url_for('tenant.dashboard'))

        elif role == 'service_provider':
            return redirect(url_for('service_provider.service_list'))

        else:
            flash("Unrecognized role. Contact system administrator.", "danger")
            return redirect(url_for('auth.logout'))

    @app.before_request
    def check_maintenance():
        try:
            mode = SystemSetting.get('maintenance_mode', '0') == '1'
            start = SystemSetting.get('maintenance_start', '')
            end = SystemSetting.get('maintenance_end', '')

            scheduled = False
            if start and end:
                try:
                    sdt = datetime.fromisoformat(start)
                    edt = datetime.fromisoformat(end)
                    now_dt = datetime.now()
                    if sdt <= now_dt <= edt:
                        scheduled = True
                except Exception:
                    scheduled = False

            if not (mode or scheduled):
                return None

            if current_user.is_authenticated and is_approved_admin(current_user):
                return None

            if request.path.startswith('/static') or request.endpoint in (
                'auth.login', 'auth.signup', 'auth.semantic_admin_entry'
            ):
                return None

            if request.endpoint and str(request.endpoint).startswith('admin.'):
                return None

            return render_template('maintenance.html'), 503

        except Exception as e:
            try:
                db.session.rollback()
            except Exception:
                pass

            app.logger.error(f"Error checking maintenance mode: {e}")

            if session.get('is_impersonating'):
                if request.method not in ('GET', 'HEAD', 'OPTIONS'):
                    return ("Action disabled while impersonating.", 403)

            return None

    return app, socketio


# =========================
# CREATE APP
# =========================
app, socketio = create_app()

# IMPORTANT: socket events
with app.app_context():
    import events.chat_events


# =========================
# RUN
# =========================
if __name__ == '__main__':
    socketio.run(app, debug=True, use_reloader=False)