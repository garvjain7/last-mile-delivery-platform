# Admin email templates (§9).
# All functions send after commit — SMTP failure is logged, never raised.
# Uses the existing aiosmtplib + config pattern from services/core_api/app/auth/email.py.
#
# Templates:
#   send_staff_invite          — new staff user invited (dispatcher/fleet_manager/admin)
#   send_merchant_owner_invite — new user created as merchant owner
#   send_merchant_access_notify — existing user given merchant access (no token)
#   send_driver_approved       — driver status changed to offline (approved)
#   send_driver_rejected       — driver status changed to rejected (+optional reason)
#
# All produce plain-text + HTML multipart messages.
# Fix 7: SMTP calls include a 10-second timeout.
# Fix 10: All user-supplied values are HTML-escaped before interpolation into HTML bodies.

from __future__ import annotations

import html
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import aiosmtplib

from services.core_api.app.config import config

logger = logging.getLogger(__name__)

_BRAND = "LOGIPULSE"
_SMTP_TIMEOUT = 10  # Fix 7: 10-second timeout for all SMTP operations


def _esc(value: str) -> str:
    """HTML-escape a user-supplied string before inserting into HTML email bodies."""
    return html.escape(str(value), quote=True)


def _make_message(to_address: str, subject: str, text: str, html_body: str) -> MIMEMultipart:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = config.smtp_user
    msg["To"] = to_address
    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html_body, "html"))
    return msg


async def _send(to_address: str, subject: str, text: str, html_body: str) -> bool:
    """Send and return True on success. Log error and return False on failure."""
    try:
        msg = _make_message(to_address, subject, text, html_body)
        await aiosmtplib.send(
            msg,
            hostname=config.smtp_host,
            port=config.smtp_port,
            username=config.smtp_user,
            password=config.smtp_password,
            start_tls=True,
            timeout=_SMTP_TIMEOUT,  # Fix 7: explicit 10-second SMTP timeout
        )
        return True
    except Exception:
        logger.exception("SMTP failure sending to %s (subject: %s)", to_address, subject)
        return False


# ---------------------------------------------------------------------------
# §9.1 Staff invite
# ---------------------------------------------------------------------------

async def send_staff_invite(
    to_address: str,
    full_name: str,
    role: str,
    reset_token: str,
) -> bool:
    """Invite link for a newly created dispatcher / fleet_manager / admin account.
    Appends invite=1 so the reset-password page shows "Set your password"."""
    invite_url = (
        f"{config.public_base_url}/reset-password?token={reset_token}&invite=1"
    )
    role_label = role.replace("_", " ").title()
    subject = f"You've been invited to {_BRAND}"
    text = (
        f"Hi {full_name},\n\n"
        f"You've been invited to {_BRAND} as {role_label}.\n\n"
        f"Set your password here (valid 72 hours, single use):\n{invite_url}\n\n"
        f"If you didn't expect this, you can ignore this email.\n\n"
        f"— {_BRAND}"
    )
    # Fix 10: HTML-escape user-supplied values
    html_body = (
        f"<p>Hi {_esc(full_name)},</p>"
        f"<p>You've been invited to <strong>{_BRAND}</strong> as <strong>{_esc(role_label)}</strong>.</p>"
        f"<p><a href='{_esc(invite_url)}'>Set your password</a> (valid 72 hours, single use).</p>"
        f"<p>If you didn't expect this, you can ignore this email.</p>"
        f"<p>— {_BRAND}</p>"
    )
    return await _send(to_address, subject, text, html_body)


# ---------------------------------------------------------------------------
# §9.2 Merchant owner invite
# ---------------------------------------------------------------------------

async def send_merchant_owner_invite(
    to_address: str,
    full_name: str,
    merchant_name: str,
    reset_token: str,
) -> bool:
    """Invite link for a newly created merchant owner account."""
    invite_url = (
        f"{config.public_base_url}/reset-password?token={reset_token}&invite=1"
    )
    subject = f"Your {_BRAND} merchant account is ready"
    text = (
        f"Hi {full_name},\n\n"
        f"Your merchant account for {merchant_name} on {_BRAND} is ready.\n\n"
        f"Set your password here (valid 72 hours, single use):\n{invite_url}\n\n"
        f"— {_BRAND}"
    )
    html_body = (
        f"<p>Hi {_esc(full_name)},</p>"
        f"<p>Your merchant account for <strong>{_esc(merchant_name)}</strong> on <strong>{_BRAND}</strong> is ready.</p>"
        f"<p><a href='{_esc(invite_url)}'>Set your password</a> (valid 72 hours, single use).</p>"
        f"<p>— {_BRAND}</p>"
    )
    return await _send(to_address, subject, text, html_body)


# ---------------------------------------------------------------------------
# §9.3 Existing user given merchant access
# ---------------------------------------------------------------------------

async def send_merchant_access_notify(
    to_address: str,
    full_name: str,
    merchant_name: str,
) -> bool:
    """Notification only — no invite token — when an existing account gets merchant access."""
    subject = f"You've been added to {merchant_name} on {_BRAND}"
    login_url = f"{config.public_base_url}/login"
    text = (
        f"Hi {full_name},\n\n"
        f"Your account has been given access to the merchant organisation "
        f"{merchant_name} on {_BRAND}.\n\n"
        f"Log in at {login_url} to get started.\n\n"
        f"— {_BRAND}"
    )
    html_body = (
        f"<p>Hi {_esc(full_name)},</p>"
        f"<p>Your account has been given access to the merchant organisation "
        f"<strong>{_esc(merchant_name)}</strong> on <strong>{_BRAND}</strong>.</p>"
        f"<p><a href='{_esc(login_url)}'>Log in</a> to get started.</p>"
        f"<p>— {_BRAND}</p>"
    )
    return await _send(to_address, subject, text, html_body)


# ---------------------------------------------------------------------------
# §9.5 Driver approved / rejected
# ---------------------------------------------------------------------------

async def send_driver_approved(to_address: str, full_name: str) -> bool:
    subject = f"Your {_BRAND} driver application has been approved"
    text = (
        f"Hi {full_name},\n\n"
        f"Your driver application has been reviewed and approved. "
        f"You can now log in and accept delivery assignments.\n\n"
        f"— {_BRAND}"
    )
    html_body = (
        f"<p>Hi {_esc(full_name)},</p>"
        f"<p>Your driver application has been reviewed and <strong>approved</strong>. "
        f"You can now log in and accept delivery assignments.</p>"
        f"<p>— {_BRAND}</p>"
    )
    return await _send(to_address, subject, text, html_body)


async def send_driver_rejected(
    to_address: str, full_name: str, reason: Optional[str] = None
) -> bool:
    subject = f"Your {_BRAND} driver application"
    reason_text = f"\n\nReason: {reason}" if reason else ""
    reason_html = f"<p><strong>Reason:</strong> {_esc(reason)}</p>" if reason else ""
    text = (
        f"Hi {full_name},\n\n"
        f"We have reviewed your driver application and are unable to approve it at this time.{reason_text}\n\n"
        f"If you have questions, please contact support.\n\n"
        f"— {_BRAND}"
    )
    html_body = (
        f"<p>Hi {_esc(full_name)},</p>"
        f"<p>We have reviewed your driver application and are unable to approve it at this time.</p>"
        f"{reason_html}"
        f"<p>If you have questions, please contact support.</p>"
        f"<p>— {_BRAND}</p>"
    )
    return await _send(to_address, subject, text, html_body)
