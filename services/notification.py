import threading
import queue
import time
import logging

logger = logging.getLogger(__name__)

# Simple in-process background queue for best-effort tasks (emails)
_task_queue = queue.Queue()
_worker_started = False
_worker_app = None


def _worker_loop():
    while True:
        try:
            task = _task_queue.get()
            if task is None:
                break
            func, kwargs = task
            try:
                if _worker_app is not None:
                    with _worker_app.app_context():
                        func(**kwargs)
                else:
                    func(**kwargs)
            except Exception:
                logger.exception('Background task failed')
            finally:
                _task_queue.task_done()
        except Exception:
            logger.exception('Worker loop error')
        # small sleep to avoid tight loop in edge cases
        time.sleep(0.01)


def start_worker(app=None):
    global _worker_started, _worker_app
    if app is not None:
        _worker_app = app
    if _worker_started:
        return
    t = threading.Thread(target=_worker_loop, daemon=True)
    t.start()
    _worker_started = True
    logger.info('Notification worker started')


def enqueue_support_email(full_name: str, sender_email: str, phone: str, role: str, message: str):
    """Enqueue a support email to be sent in background. Non-blocking."""
    try:
        # We pass the actual send function via import at worker runtime; here just wrap params
        from utils_email_2fa import send_support_contact_email
        _task_queue.put((send_support_contact_email, {
            'full_name': full_name,
            'sender_email': sender_email,
            'phone': phone,
            'role': role,
            'message': message,
        }))
    except Exception:
        logger.exception('Failed to enqueue support email')


def enqueue_system_update_email(recipient_email: str, title: str, body: str):
    """Enqueue a platform/system update email to be sent in background."""
    try:
        from utils_email_2fa import send_system_update_email
        _task_queue.put((send_system_update_email, {
            'recipient_email': recipient_email,
            'title': title,
            'body': body,
        }))
    except Exception:
        logger.exception('Failed to enqueue system update email')


def enqueue_password_reset_email(recipient_email: str, recipient_name: str, reset_url: str, expires_minutes: int = 60):
    """Enqueue a password reset email to be sent in background."""
    try:
        from utils_email_2fa import send_password_reset_email
        _task_queue.put((send_password_reset_email, {
            'recipient_email': recipient_email,
            'recipient_name': recipient_name,
            'reset_url': reset_url,
            'expires_minutes': expires_minutes,
        }))
    except Exception:
        logger.exception('Failed to enqueue password reset email')
