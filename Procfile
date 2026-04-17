release: flask db upgrade
web: gunicorn wsgi:app --worker-class eventlet -w 1
