"""Payment receipts uploaded with top-up requests: type detection from the bytes and safe serving."""

import base64
import binascii

from fastapi import Response

from app.core.errors import AppError
from app.models import TopUpRequest

MAX_RECEIPT_BYTES = 5 * 1024 * 1024
INLINE_TYPES = {"image/png", "image/jpeg", "image/webp"}


def sniff(data: bytes) -> str | None:
    """The receipt's real type from its magic bytes (the file name and browser-sent type are not trusted)."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    return None


def decode(content_base64: str) -> tuple[bytes, str]:
    try:
        data = base64.b64decode(content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise AppError("Receipt is not valid base64") from exc
    if not data:
        raise AppError("Receipt is empty")
    if len(data) > MAX_RECEIPT_BYTES:
        raise AppError("Receipt is larger than 5 MB", code="receipt_too_large")
    kind = sniff(data)
    if kind is None:
        raise AppError("Receipt must be a PNG, JPEG, WEBP image or a PDF", code="unsupported_receipt")
    return data, kind


def response(topup: TopUpRequest) -> Response:
    """Images open inline; PDFs download. Sandboxed so an uploaded file can never run script on our origin."""
    kind = topup.receipt_content_type or "application/octet-stream"
    disposition = "inline" if kind in INLINE_TYPES else "attachment"
    return Response(
        content=topup.receipt_data or b"",
        media_type=kind,
        headers={
            "Content-Disposition": f'{disposition}; filename="receipt-{topup.id}"',
            "Content-Security-Policy": "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; sandbox",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )
