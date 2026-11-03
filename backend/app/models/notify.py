"""Notifications (services/notify): the in-app inbox, the email/Telegram outbox and admin broadcasts."""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JSONType, Timestamps, UUIDPk, utcnow


class Notification(UUIDPk, Timestamps, Base):
    """One message for one user. Title and body are rendered in the user's language when created."""

    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_read_created", "user_id", "read_at", "created_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(40), index=True)
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str | None] = mapped_column(String(500))
    # Values the email and Telegram renderers need (amounts, names...); never secrets.
    params: Mapped[dict] = mapped_column(JSONType, default=dict)
    broadcast_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("broadcasts.id", ondelete="SET NULL"))
    # False when the bell channel is off for this kind: the row then only carries the email/Telegram deliveries.
    in_app: Mapped[bool] = mapped_column(default=True, server_default="true")
    read_at: Mapped[datetime | None]


class NotificationDelivery(UUIDPk, Timestamps, Base):
    """Outbox row: one email or Telegram send, retried with backoff by the notify worker."""

    __tablename__ = "notification_deliveries"
    __table_args__ = (Index("ix_notification_deliveries_due", "status", "next_attempt_at"),)

    notification_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("notifications.id", ondelete="CASCADE"), index=True)
    channel: Mapped[str] = mapped_column(String(16))  # NotifyChannel.EMAIL / TELEGRAM
    status: Mapped[str] = mapped_column(String(10), default="pending")  # DeliveryStatus
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_error: Mapped[str | None] = mapped_column(String(500))
    sent_at: Mapped[datetime | None]


class Broadcast(UUIDPk, Timestamps, Base):
    """A message the platform admin sent to an audience (services/notify/broadcast.py)."""

    __tablename__ = "broadcasts"

    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(20))  # announcement | marketing
    title_ar: Mapped[str] = mapped_column(String(300), default="")
    title_en: Mapped[str] = mapped_column(String(300), default="")
    body_ar: Mapped[str] = mapped_column(Text, default="")
    body_en: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str | None] = mapped_column(String(500))
    audience: Mapped[dict] = mapped_column(JSONType, default=dict)  # {"type": ..., "ids": [...]}
    channels: Mapped[list] = mapped_column(JSONType, default=list)
    status: Mapped[str] = mapped_column(String(12), default="sending")  # sending | sent
    recipients: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
