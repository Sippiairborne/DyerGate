import logging
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger("dyergate.email")


async def send_email(to: str, subject: str, html: str, text: Optional[str] = None) -> bool:
    """Send via Resend if configured; otherwise log only."""
    if not getattr(settings, "RESEND_API_KEY", ""):
        logger.info("[email-stub] to=%s subject=%s", to, subject)
        return True
    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            r = await http.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
                json={
                    "from": getattr(settings, "EMAIL_FROM", "DyerGate <noreply@dyergate.io>"),
                    "to": [to],
                    "subject": subject,
                    "html": html,
                    "text": text or html,
                },
            )
            return 200 <= r.status_code < 300
    except Exception as e:
        logger.exception("email send failed: %s", e)
        return False


def render_low_balance_email(client_identity: str, balance: float, threshold: float) -> tuple[str, str]:
    subject = f"[DyerGate] Low balance alert for {client_identity}"
    html = f"""
    <h2>Low balance warning</h2>
    <p>Client <b>{client_identity}</b> has dropped below the alert threshold.</p>
    <ul>
      <li>Current balance: <b>${balance:.4f}</b></li>
      <li>Threshold: ${threshold:.4f}</li>
    </ul>
    <p>Top up via the admin dashboard to avoid request failures.</p>
    """
    return subject, html


def render_payment_receipt(client_identity: str, amount_usd: float, credits: float, balance: float) -> tuple[str, str]:
    subject = f"[DyerGate] Payment received — ${amount_usd:.2f}"
    html = f"""
    <h2>Payment received</h2>
    <p>Thank you! Your payment of <b>${amount_usd:.2f}</b> added <b>{credits:.2f}</b> credits.</p>
    <p>New balance: <b>${balance:.4f}</b></p>
    """
    return subject, html
