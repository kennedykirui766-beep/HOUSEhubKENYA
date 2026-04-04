import time

from flask import current_app, session


def consume_rate_limit(bucket_key, limit, window_seconds):
    """Return whether the current session is under the configured rate limit."""
    now = int(time.time())
    buckets = session.get("rate_limit_buckets", {})
    timestamps = [ts for ts in buckets.get(bucket_key, []) if now - ts < window_seconds]

    if len(timestamps) >= limit:
        retry_after = window_seconds - (now - min(timestamps))
        buckets[bucket_key] = timestamps
        session["rate_limit_buckets"] = buckets
        session.modified = True
        return False, max(1, retry_after)

    timestamps.append(now)
    buckets[bucket_key] = timestamps
    session["rate_limit_buckets"] = buckets
    session.modified = True
    return True, 0


def get_allowed_admin_email():
    return (current_app.config.get("ADMIN_EMAIL") or "").strip().lower()


def is_approved_admin(user):
    if not user or not getattr(user, "role", None):
        return False

    if user.role.lower() != "admin":
        return False

    allowed_email = get_allowed_admin_email()
    if not allowed_email:
        return False

    return (user.email or "").strip().lower() == allowed_email


def mark_admin_totp_verified(user):
    session["admin_totp_verified_for"] = user.id
    session["admin_totp_verified_at"] = int(time.time())
    session.modified = True


def clear_admin_totp_verification():
    session.pop("admin_totp_verified_for", None)
    session.pop("admin_totp_verified_at", None)


def has_admin_totp_verified(user):
    return session.get("admin_totp_verified_for") == getattr(user, "id", None)
