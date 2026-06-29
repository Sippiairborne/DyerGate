import logging
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import UsageLedger, ForecastRun

logger = logging.getLogger("dyergate.forecast")


def _daily_aggregate(db: Session, org_id: int, days: int) -> list[dict]:
    """Return daily totals for the past `days` days."""
    since = datetime.utcnow() - timedelta(days=days)
    rows = (
        db.query(
            func.strftime("%Y-%m-%d", UsageLedger.created_at).label("day"),
            func.coalesce(func.sum(UsageLedger.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(UsageLedger.output_tokens), 0).label("output_tokens"),
            func.coalesce(func.sum(UsageLedger.total_cost), 0.0).label("cost"),
            func.count(UsageLedger.id).label("requests"),
        )
        .filter(UsageLedger.org_id == org_id, UsageLedger.created_at >= since)
        .group_by("day")
        .order_by("day")
        .all()
    )
    return [{
        "day": r.day, "input_tokens": int(r.input_tokens),
        "output_tokens": int(r.output_tokens),
        "cost": float(r.cost), "requests": int(r.requests),
    } for r in rows]


def forecast(db: Session, org_id: int, horizon_days: int = 30,
             lookback_days: int = 90) -> ForecastRun:
    """Linear regression on daily cost → predict next N days."""
    from app.config import settings
    history = _daily_aggregate(db, org_id, lookback_days)
    if len(history) < 7:
        # Not enough data — use simple averaging
        if not history:
            daily_avg_cost = 0.0
            daily_avg_in = 0
            daily_avg_out = 0
            daily_avg_req = 0
        else:
            daily_avg_cost = sum(r["cost"] for r in history) / len(history)
            daily_avg_in = sum(r["input_tokens"] for r in history) / len(history)
            daily_avg_out = sum(r["output_tokens"] for r in history) / len(history)
            daily_avg_req = sum(r["requests"] for r in history) / len(history)
        daily_pred = [{
            "day": (datetime.utcnow() + timedelta(days=i + 1)).strftime("%Y-%m-%d"),
            "cost": round(daily_avg_cost, 4),
        } for i in range(horizon_days)]
        run = ForecastRun(
            org_id=org_id, horizon_days=horizon_days,
            predicted_total_cost=daily_avg_cost * horizon_days,
            predicted_input_tokens=int(daily_avg_in * horizon_days),
            predicted_output_tokens=int(daily_avg_out * horizon_days),
            predicted_requests=int(daily_avg_req * horizon_days),
            daily_forecast=daily_pred,
            confidence_low=daily_avg_cost * horizon_days * 0.7,
            confidence_high=daily_avg_cost * horizon_days * 1.3,
            model_used="simple_average",
        )
        db.add(run); db.commit(); db.refresh(run)
        return run

    # Linear regression on cost over time
    y = np.array([r["cost"] for r in history])
    x = np.arange(len(y))
    slope, intercept = np.polyfit(x, y, 1)
    future_x = np.arange(len(y), len(y) + horizon_days)
    future_y = slope * future_x + intercept
    future_y = np.maximum(future_y, 0)  # clamp negatives
    daily_pred = [{
        "day": (datetime.utcnow() + timedelta(days=i + 1)).strftime("%Y-%m-%d"),
        "cost": round(float(v), 4),
    } for i, v in enumerate(future_y)]

    predicted_total = float(future_y.sum())
    avg_in = sum(r["input_tokens"] for r in history) / len(history)
    avg_out = sum(r["output_tokens"] for r in history) / len(history)
    avg_req = sum(r["requests"] for r in history) / len(history)
    std_cost = float(np.std(y)) if len(y) > 1 else 0.0

    run = ForecastRun(
        org_id=org_id, horizon_days=horizon_days,
        predicted_total_cost=predicted_total,
        predicted_input_tokens=int(avg_in * horizon_days),
        predicted_output_tokens=int(avg_out * horizon_days),
        predicted_requests=int(avg_req * horizon_days),
        daily_forecast=daily_pred,
        confidence_low=max(0.0, predicted_total - std_cost * horizon_days * 1.96),
        confidence_high=predicted_total + std_cost * horizon_days * 1.96,
        model_used="linear_regression",
    )
    db.add(run); db.commit(); db.refresh(run)
    return run
