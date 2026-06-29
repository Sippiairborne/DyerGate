from datetime import datetime, timedelta

from sqlalchemy import func, case
from sqlalchemy.orm import Session

from app.models import UsageLedger, AgentInvocation, ClientAccount


def timeseries(db: Session, org_id: int, days: int = 30, granularity: str = "day") -> list[dict]:
    """Returns per-bucket usage: tokens in/out, cost, requests."""
    if granularity == "hour":
        bucket = func.strftime("%Y-%m-%d %H:00:00", UsageLedger.created_at) if db.bind.dialect.name == "sqlite" \
            else func.date_trunc("hour", UsageLedger.created_at)
    else:
        bucket = func.strftime("%Y-%m-%d", UsageLedger.created_at) if db.bind.dialect.name == "sqlite" \
            else func.date_trunc("day", UsageLedger.created_at)
    since = datetime.utcnow() - timedelta(days=days)
    rows = (
        db.query(
            bucket.label("bucket"),
            func.coalesce(func.sum(UsageLedger.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(UsageLedger.output_tokens), 0).label("output_tokens"),
            func.coalesce(func.sum(UsageLedger.total_cost), 0.0).label("cost"),
            func.count(UsageLedger.id).label("requests"),
            func.sum(case((UsageLedger.success == False, 1), else_=0)).label("errors"),
        )
        .filter(UsageLedger.org_id == org_id, UsageLedger.created_at >= since)
        .group_by("bucket")
        .order_by("bucket")
        .all()
    )
    return [{
        "bucket": str(r.bucket),
        "input_tokens": int(r.input_tokens),
        "output_tokens": int(r.output_tokens),
        "cost": float(r.cost),
        "requests": int(r.requests),
        "errors": int(r.errors or 0),
    } for r in rows]


def by_model(db: Session, org_id: int, days: int = 30) -> list[dict]:
    since = datetime.utcnow() - timedelta(days=days)
    rows = (
        db.query(
            UsageLedger.model,
            func.count(UsageLedger.id).label("requests"),
            func.coalesce(func.sum(UsageLedger.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(UsageLedger.output_tokens), 0).label("output_tokens"),
            func.coalesce(func.sum(UsageLedger.total_cost), 0.0).label("cost"),
            func.avg(case((UsageLedger.success == True, 1.0), else_=0.0)).label("success_rate"),
        )
        .filter(UsageLedger.org_id == org_id,
                UsageLedger.created_at >= since,
                UsageLedger.model.isnot(None))
        .group_by(UsageLedger.model)
        .order_by(func.sum(UsageLedger.total_cost).desc())
        .all()
    )
    return [{
        "model": r.model,
        "requests": int(r.requests),
        "input_tokens": int(r.input_tokens),
        "output_tokens": int(r.output_tokens),
        "cost": float(r.cost),
        "success_rate": float(r.success_rate or 0.0),
    } for r in rows]


def by_endpoint(db: Session, org_id: int, days: int = 30) -> list[dict]:
    since = datetime.utcnow() - timedelta(days=days)
    rows = (
        db.query(
            UsageLedger.endpoint,
            func.count(UsageLedger.id).label("requests"),
            func.coalesce(func.sum(UsageLedger.total_cost), 0.0).label("cost"),
        )
        .filter(UsageLedger.org_id == org_id, UsageLedger.created_at >= since)
        .group_by(UsageLedger.endpoint)
        .all()
    )
    return [{"endpoint": r.endpoint, "requests": int(r.requests), "cost": float(r.cost)} for r in rows]


def top_clients(db: Session, org_id: int, days: int = 30, limit: int = 10) -> list[dict]:
    since = datetime.utcnow() - timedelta(days=days)
    rows = (
        db.query(
            ClientAccount.id, ClientAccount.client_identity,
            func.count(UsageLedger.id).label("requests"),
            func.coalesce(func.sum(UsageLedger.total_cost), 0.0).label("cost"),
        )
        .join(UsageLedger, UsageLedger.client_id == ClientAccount.id)
        .filter(UsageLedger.org_id == org_id, UsageLedger.created_at >= since)
        .group_by(ClientAccount.id)
        .order_by(func.sum(UsageLedger.total_cost).desc())
        .limit(limit)
        .all()
    )
    return [{
        "client_id": r.id, "client_identity": r.client_identity,
        "requests": int(r.requests), "cost": float(r.cost),
    } for r in rows]
