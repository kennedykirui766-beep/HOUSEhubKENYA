import threading
import queue
import time
import logging

logger = logging.getLogger(__name__)

# Simple in-process background queue for best-effort tasks (emails)
_task_queue = queue.Queue()
_worker_started = False


def _worker_loop():
    from utils_email_2fa import send_support_contact_email
    while True:
        try:
            task = _task_queue.get()
            if task is None:
                break
            func, kwargs = task
            try:
                func(**kwargs)
            except Exception:
                logger.exception('Background task failed')
            finally:
                _task_queue.task_done()
        except Exception:
            logger.exception('Worker loop error')
        # small sleep to avoid tight loop in edge cases
        time.sleep(0.01)


def start_worker():
    global _worker_started
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
