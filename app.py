from flask import Flask, redirect, url_for, flash, render_template, request
from config import Config
from extensions import db, migrate, login_manager, csrf
from flask_socketio import SocketIO
from flask_cors import CORS
from models.models import User, House, ChatMessage, SupportTicket  # Added SupportTicket
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError
from datetime import datetime
import os
import logging

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    
    # Ensure critical configurations are set
    app.config['SECRET_KEY'] = app.config.get('SECRET_KEY', 'your-secure-secret-key')
    app.config['SQLALCHEMY_DATABASE_URI'] = app.config.get('SQLALCHEMY_DATABASE_URI', 'sqlite:///app.db')
    app.config['UPLOAD_FOLDER'] = app.config.get('UPLOAD_FOLDER', 'static/images')
    app.config['CHAT_UPLOAD_FOLDER'] = app.config.get('CHAT_UPLOAD_FOLDER', 'static/uploads/chat')
    app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif', 'pdf'}  # For chat file uploads
    app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5MB file size limit
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Setup logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    print("Final DB URI =", app.config['SQLALCHEMY_DATABASE_URI'])
    print("UPLOAD_FOLDER =", app.config['UPLOAD_FOLDER'])
    print("CHAT_UPLOAD_FOLDER =", app.config['CHAT_UPLOAD_FOLDER'])

    # Create chat upload directory
    os.makedirs(app.config['CHAT_UPLOAD_FOLDER'], exist_ok=True)

    # Init extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    socketio = SocketIO(app, cors_allowed_origins="*")
    CORS(app)

    # Exempt Socket.IO routes from CSRF (since chat.html uses WebSocket)
    csrf.exempt('routes.support_routes.support_bp')

    # Login manager configuration
    @login_manager.user_loader
    def load_user(user_id):
        try:
            return User.query.get(int(user_id))
        except Exception as e:
            logger.error(f"Error loading user {user_id}: {str(e)}")
            return None

    # Jinja filters
    def timeago(value):
        """Format datetime into 'time ago' string with localization (English/Swahili)."""
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
        """Format datetime into a standard string (default: 2025-08-27 14:30)."""
        if not isinstance(value, datetime):
            return value
        return value.strftime(format)

    # Register filters
    app.jinja_env.filters['timeago'] = timeago
    app.jinja_env.filters['datetimeformat'] = datetimeformat

    # Blueprints
    from routes.auth_routes import auth_bp
    from routes.landlord_routes import landlord_bp
    from routes.tenant_routes import tenant_bp
    from routes.admin_routes import admin_bp
    from routes.service_routes import service_provider_bp
    from routes.house_routes import house_bp
    from routes.main import main_bp
    from routes.support_routes import support_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(landlord_bp)
    app.register_blueprint(tenant_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(service_provider_bp)
    app.register_blueprint(house_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(support_bp)

    # Routes
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

    @app.route("/subscribe", methods=["POST"])
    def subscribe():
        email = request.form.get("email")
        if email:
            try:
                # TODO: save email to DB or send confirmation
                logger.info(f"Subscription attempt with email: {email}")
                flash(f"Subscribed successfully with {email}", "success")
            except Exception as e:
                logger.error(f"Error processing subscription: {str(e)}")
                flash("Error processing subscription.", "danger")
        else:
            flash("No email provided", "danger")
        return redirect(url_for("index"))

    # Central portal for role-based redirect
    @app.route('/portal')
    @login_required
    def portal():
        role = current_user.role.lower()
        logger.info(f"User {current_user.id} accessing portal with role: {role}")
        if role == 'admin':
            return redirect(url_for('admin.manage_users'))
        elif role == 'landlord':
            return redirect(url_for('landlord.dashboard'))
        elif role == 'tenant':
            return redirect(url_for('tenant.dashboard'))
        elif role == 'service_provider':
            return redirect(url_for('service_provider.service_list')) 
        else:
            logger.warning(f"Unrecognized role for user {current_user.id}: {role}")
            flash("Unrecognized role. Contact system administrator.", "danger")
            return redirect(url_for('auth.logout'))

    return app, socketio

# Create app and socketio
app, socketio = create_app()

# Run
if __name__ == '__main__':
    with app.app_context():
        try:
            db.create_all()  # Create tables if needed
        except Exception as e:
            app.logger.error(f"Error creating database tables: {str(e)}")
    socketio.run(app, debug=True, use_reloader=False)