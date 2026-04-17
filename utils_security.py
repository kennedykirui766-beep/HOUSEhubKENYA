import time
import ipaddress

from flask import current_app, session, request


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


def get_request_ip():
    """Best-effort client IP extraction supporting reverse-proxy headers."""
    xff = (request.headers.get("X-Forwarded-For") or "").strip()
    if xff:
        # Standard format is client, proxy1, proxy2...
        first = xff.split(",")[0].strip()
        if first:
            return first
    return (request.remote_addr or "").strip()


def get_admin_ip_allowlist():
    raw = (current_app.config.get("ADMIN_IP_ALLOWLIST") or "").strip()
    if not raw:
        return []
    return [entry.strip() for entry in raw.split(",") if entry.strip()]


def is_admin_ip_allowed(ip_text):
    """Return True if IP is allowed by ADMIN_IP_ALLOWLIST. Empty list means allow all."""
    allowlist = get_admin_ip_allowlist()
    if not allowlist:
        return True

    try:
        client_ip = ipaddress.ip_address(ip_text)
    except Exception:
        return False

    for entry in allowlist:
        try:
            if "/" in entry:
                net = ipaddress.ip_network(entry, strict=False)
                if client_ip in net:
                    return True
            else:
                if client_ip == ipaddress.ip_address(entry):
                    return True
        except Exception:
            # Ignore malformed allowlist entries and continue checking others.
            continue

    return False
