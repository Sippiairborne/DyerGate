import logging
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Organization, UsageLedger
from app.config import settings

logger = logging.getLogger("dyergate.quota")


def org_spend_window(db: Session, org_id: int, days: int = 30) -> float:
    """Sum of total_cost for an org in the last N days."""
    since = datetime.utcnow() - timedelta(days=days)
    val = (
        db.query(func.coalesce(func.sum(UsageLedger.total_cost), 0.0))
        .filter(UsageLedger.org_id == org_id, UsageLedger.created_at >= since)
        .scalar()
    )
    return float(val or 0.0)


def enforce_quota(db: Session, org_id: int, additional_cost: float) -> None:
    """
    Refuse the request if accepting it would push the org's 30-day spend over its quota.
    Also accounts for outstanding (held) credit balances.
    """
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found.")
    if not org.is_active:
        raise HTTPException(status_code=403, detail="Organization disabled.")

    spent = org_spend_window(db, org_id)
    if spent + additional_cost > org.quota_usd:
        raise HTTPException(
            status_code=402,
            detail=(
                f"Org quota exceeded: spent_30d=${spent:.4f} + "
                f"this_request≈${additional_cost:.4f} > quota=${org.quota_usd:.4f}. "
                "Contact admin to raise quota or add credits."
            ),
        )


def quota_snapshot(db: Session, org_id: int) -> dict:
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        return {"org_id": org_id, "exists": False}
    spent = org_spend_window(db, org_id)
    return {
        "org_id": org.id,
        "org_name": org.name,
        "quota_usd": org.quota_usd,
        "spent_30d_usd": spent,
        "remaining_usd": max(0.0, org.quota_usd - spent),
        "utilization_pct": round((spent / org.quota_usd) * 100, 2) if org.quota_usd > 0 else 0.0,
    }
