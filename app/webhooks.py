
import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models import ClientAccount, ClientWebhook, AlertLog, Payment

logger = logging.getLogger("dyergate.webhooks")


def _sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def _deliver(url: str, secret: str, event_type: str, payload: dict) -> tuple[bool, int | None, str | None]:
    body = json.dumps({
        "event": event_type,
        "delivered_at": datetime.utcnow().isoformat(),
        "data": payload,
    }, separators=(",", ":")).encode("utf-8")
    sig = _sign(secret, body)
    headers = {
        "Content-Type": "application/json",
        "X-DyerGate-Event": event_type,
        "X-DyerGate-Signature": f"sha256={sig}",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            r = await http.post(url, content=body, headers=headers)
        return (200 <= r.status_code < 300), r.status_code, None
    except Exception as e:
        return False, None, str(e)


async def fire_event(
    db: Session,
    client: ClientAccount | None,
    event_type: str,
    payload: dict,
) -> int:
    """Fan out an event to all subscribed webhooks + global alert URL. Returns count delivered."""
    delivered = 0
    targets: list[tuple[str, str]] = []

    if client is not None:
        for sub in client.webhooks:
            if sub.is_active and event_type in (sub.event_types or "").split(","):
                targets.append((sub.url, sub.secret))

    if settings.ALERT_WEBHOOK_URL and event_type.startswith(("low_balance", "payment")):
        targets.append((settings.ALERT_WEBHOOK_URL, settings.ALERT_WEBHOOK_SECRET))

    for url, secret in targets:
        ok, status, err = await _deliver(url, secret, event_type, payload)
        log = AlertLog(
            client_id=client.id if client else None,
            event_type=event_type,
            payload=json.dumps(payload)[:4000],
            delivered=ok,
            response_status=status,
            error=err,
        )
        db.add(log)
        if ok:
            delivered += 1
    try:
        db.commit()
    except Exception:
        db.rollback()
    return delivered


async def check_low_balance_and_alert(db: Session, client: ClientAccount) -> None:
    """Call after any operation that changes client balance."""
    if client.credit_balance > settings.LOW_BALANCE_THRESHOLD:
        return
    now = datetime.utcnow()
    if client.last_low_balance_alert_at and (now - client.last_low_balance_alert_at) < timedelta(hours=6):
        return  # throttle alerts
    client.last_low_balance_alert_at = now
    db.commit()
    await fire_event(
        db,
        client,
        event_type="low_balance",
        payload={
            "client_identity": client.client_identity,
            "credit_balance": client.credit_balance,
            "threshold": settings.LOW_BALANCE_THRESHOLD,
            "auto_topup_enabled": client.auto_topup_enabled,
        },
    )
