"""Thin wrapper around the Resend API.

Deliberately the only place `resend` is imported: everything else in this
module works with plain `(to, subject, text)` strings, so it stays testable
without a network call or an API key.
"""

import resend

from app.core.config import settings


class EmailNotConfigured(RuntimeError):
    """Raised when RESEND_API_KEY is unset -- see backend/.env.example."""


def send_email(to: str, subject: str, text: str) -> None:
    if not settings.resend_api_key:
        raise EmailNotConfigured(
            "RESEND_API_KEY is not set (see backend/.env.example). "
            "Sign up at https://resend.com and put a key in backend/.env."
        )

    resend.api_key = settings.resend_api_key
    resend.Emails.send(
        {
            "from": settings.resend_from_email,
            "to": to,
            "subject": subject,
            "text": text,
        }
    )
