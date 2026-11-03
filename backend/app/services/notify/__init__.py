"""Notifications: bell, email and Telegram (see catalog.py for the kinds, dispatcher.py for `notify`)."""

from app.services.notify.dispatcher import notify, notify_admins

__all__ = ["notify", "notify_admins"]
