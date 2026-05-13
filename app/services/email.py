from __future__ import annotations

import asyncio
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


async def send_email(
    *,
    to_email: str,
    subject: str,
    body: str,
    html_body: str | None = None,
) -> bool:
    """Send an email using basic SMTP configuration.

    This is intentionally conservative: if SMTP is not configured or
    sending fails, we log and return False instead of raising so that
    email delivery does not break core application flows.
    """
    host = settings.EMAIL_SMTP_HOST
    username = settings.EMAIL_SMTP_USERNAME
    password = settings.EMAIL_SMTP_PASSWORD
    sender = settings.EMAIL_SENDER_ADDRESS
    port = settings.EMAIL_SMTP_PORT

    if not host or not username or not password or not sender:
        logger.info(
            "Email not sent: SMTP not fully configured",
            extra={"to_email": to_email, "subject": subject},
        )
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_email

    msg.attach(MIMEText(body, "plain", "utf-8"))
    if html_body:
        msg.attach(MIMEText(html_body, "html", "utf-8"))

    def _send() -> bool:
        try:
            with smtplib.SMTP(host, port) as server:
                server.starttls()
                server.login(username, password)
                server.sendmail(sender, [to_email], msg.as_string())
            return True
        except Exception as e:  # pragma: no cover - network/SMTP dependent
            logger.error(
                "Email send failed",
                extra={"to_email": to_email, "subject": subject, "error": str(e)},
            )
            return False

    return await asyncio.to_thread(lambda: _send())

