# Async email sender for password reset links.
# Uses aiosmtplib so the event loop is never blocked.
# Credentials come from SMTP_USER and SMTP_PASSWORD env vars (app passwords).

import aiosmtplib
from email.message import EmailMessage

from app.config import config


async def send_reset_email(to_address: str, reset_token: str) -> None:
    """Send a password-reset link containing the raw reset token to to_address.

    The link points at the core-api's own reset endpoint — the frontend picks up
    the token from the URL query param and POSTs it to POST /auth/reset-password.

    This is fire-and-forget from the handler's perspective: any SMTP error is
    logged and re-raised so the caller can return a 500 rather than silently
    dropping the email.
    """
    reset_url = f"{config.public_base_url}/auth/reset-password?token={reset_token}"

    msg = EmailMessage()
    msg["Subject"] = "Reset your Last-Mile Delivery password"
    msg["From"] = config.smtp_user
    msg["To"] = to_address
    msg.set_content(
        f"Hi,\n\n"
        f"We received a request to reset your password.\n\n"
        f"Click the link below (valid for 1 hour):\n{reset_url}\n\n"
        f"If you didn't request this, ignore this email — your password stays the same.\n\n"
        f"– Last-Mile Delivery Platform"
    )

    await aiosmtplib.send(
        msg,
        hostname=config.smtp_host,
        port=config.smtp_port,
        username=config.smtp_user,
        password=config.smtp_password,
        start_tls=True,
    )
