import os
import sys
import secrets

# Ensure project root is on sys.path so imports work when running this script
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app import create_app
from extensions import db
from models.models import User

ADMIN_EMAIL = "kamauemilio35@gmail.com"
NEW_PASSWORD = secrets.token_urlsafe(12)

app, _ = create_app()

with app.app_context():
    user = User.query.filter_by(email=ADMIN_EMAIL).first()
    if user:
        user.role = 'admin'
        user.set_password(NEW_PASSWORD)
        db.session.add(user)
        db.session.commit()
        print(f"Updated existing user {ADMIN_EMAIL} -> role=admin")
    else:
        admin = User(
            name='Admin',
            email=ADMIN_EMAIL,
            role='admin'
        )
        admin.set_password(NEW_PASSWORD)
        db.session.add(admin)
        db.session.commit()
        print(f"Created new admin user {ADMIN_EMAIL}")

print('Admin password:', NEW_PASSWORD)
print('Please store this password somewhere safe and change it after login.')
