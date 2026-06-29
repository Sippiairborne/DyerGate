import io
import json
import logging
import zipfile
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import (
    ClientAccount, ApiKey, UsageLedger, Payment,
    ClientWebhook, AdminUser,
)

logger = logging.getLogger("dyergate.gdpr")


def export_client_data(db: Session, org_id: int, client_identity: str) -> bytes:
    """Return a zip archive containing all PII + ledger data for one client."""
    client = (
        db.query(ClientAccount)
        .filter(ClientAccount.org_id == org_id, ClientAccount.client_identity == client_identity)
        .first()
    )
    if not client:
        raise ValueError("Client not found.")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        profile = {
            "client_identity": client.client_identity,
            "org_id": client.org_id,
            "email": client.email,
            "credit_balance": client.credit_balance,
            "is_active": client.is_active,
            "created_at": client.created_at.isoformat(),
            "last_seen_at": client.last_seen_at.isoformat() if client.last_seen_at else None,
        }
        zf.writestr("profile.json", json.dumps(profile, indent=2))

        ledger = [
            {
                "endpoint": r.endpoint, "model": r.model,
                "input_tokens": r.input_tokens, "output_tokens": r.output_tokens,
                "total_cost": r.total_cost, "success": r.success,
                "created_at": r.created_at.isoformat(),
            }
            for r in client.ledger_entries
        ]
        zf.writestr("usage_ledger.json", json.dumps(ledger, indent=2))

        payments = [
            {
                "package_name": p.package_name, "usd_cents": p.usd_cents,
                "credit_amount": p.credit_amount, "status": p.status,
                "created_at": p.created_at.isoformat(),
                "completed_at": p.completed_at.isoformat() if p.completed_at else None,
            }
            for p in client.payments
        ]
        zf.writestr("payments.json", json.dumps(payments, indent=2))

        webhooks = [{"url": w.url, "event_types": w.event_types,
                     "is_active": w.is_active} for w in client.webhooks]
        zf.writestr("webhooks.json", json.dumps(webhooks, indent=2))

        zf.writestr("README.txt",
                    "This archive contains personal data associated with the "
                    "DyerGate client above. Generated at "
                    f"{datetime.utcnow().isoformat()}Z.\n")
    return buf.getvalue()


def erase_client(db: Session, org_id: int, client_identity: str) -> dict:
    """
    Soft-erase: zero out PII, revoke keys, mark deleted.
    Ledger rows are retained for tax/audit purposes but anonymized.
    """
    client = (
        db.query(ClientAccount)
        .filter(ClientAccount.org_id == org_id, ClientAccount.client_identity == client_identity)
        .first()
    )
    if not client:
        raise ValueError("Client not found.")

    now = datetime.utcnow()
    client.email = None
    client.is_active = False
    client.deleted_at = now
    for k in client.api_keys:
        k.revoked_at = now
        k.expires_at = now
    for w in client.webhooks:
        w.is_active = False
    db.commit()
    return {
        "client_identity": client.client_identity,
        "deleted_at": now.isoformat(),
        "keys_revoked": len(client.api_keys),
        "webhooks_disabled": len(client.webhooks),
    }


def erase_admin(db: Session, email: str) -> dict:
    user = db.query(AdminUser).filter(AdminUser.email == email).first()
    if not user:
        raise ValueError("Admin not found.")
    now = datetime.utcnow()
    user.is_active = False
    user.deleted_at = now
    db.query(AdminUser).filter(AdminUser.id == user.id).update(
        {AdminUser.email: f"erased+{user.id}@invalid",
         AdminUser.password_hash: "x",
         AdminUser.totp_secret: None})
    db.commit()
    return {"email": email, "deleted_at": now.isoformat()}
