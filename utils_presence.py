"""
Presence tracking helpers.

A user is considered "online" if their `last_seen_at` timestamp is within
PRESENCE_WINDOW_SECONDS of now. `last_seen_at` is stamped by routes that
call `touch_presence()` — currently the chat poll endpoints, since that's
where presence actually matters.

Why this design:
- Chat pages poll every 4-15s, so a single `touch_presence()` call per poll
  keeps an active user "online" while their chat is open.
- When they close the tab, polling stops, the timestamp goes stale, and
  they flip to "offline" after PRESENCE_WINDOW_SECONDS — WhatsApp-style.
- No global before_request hook, so we don't write to the DB on every
  authenticated request (dashboard hits, API calls, static assets, etc.).
"""

from datetime import datetime, timedelta


# How long after the last poll before a user is considered offline.
# 2 minutes gives enough buffer for the slower idle-poll interval (15s)
# plus some network jitter, while still feeling responsive.
PRESENCE_WINDOW_SECONDS = 120


def touch_presence(user):
    """
    Mark the user as active right now.

    Call this from any route where presence matters (chat polls, and
    later optionally dashboard loads if you want a site-wide indicator).
    Does NOT commit — the caller is expected to commit, or to let the
    request lifecycle commit for them.

    Safe to call with None or an anonymous user (no-op).
    """
    if user and getattr(user, 'is_authenticated', False):
        user.last_seen_at = datetime.utcnow()


def is_user_online(user, window_seconds=PRESENCE_WINDOW_SECONDS):
    """
    Return True if the user was seen within `window_seconds`.

    A user who has never been seen (last_seen_at is None) is offline.
    """
    if not user or not user.last_seen_at:
        return False
    return (datetime.utcnow() - user.last_seen_at) < timedelta(seconds=window_seconds)


def presence_payload(user, window_seconds=PRESENCE_WINDOW_SECONDS):
    """
    Build the JSON-friendly presence object for a single user.

    Used by poll_messages to construct the per-peer presence map.
    Returns None if the user doesn't exist, so callers can skip it.
    """
    if not user:
        return None
    return {
        "online": is_user_online(user, window_seconds),
        "last_seen": user.last_seen_at.isoformat() if user.last_seen_at else None,
    }