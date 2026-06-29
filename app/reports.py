import csv
import io
import json
import logging
from datetime import datetime, timedelta

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Organization, ClientAccount, UsageLedger, ScheduledReport
from app.archive import _get_s3
from app.webhooks import fire_event

logger = logging.getLogger("dyergate.reports")


def _date_range(cadence: str) -> tuple[datetime, datetime]:
    now = datetime.utcnow()
    if cadence == "daily":
        return now - timedelta(days=1), now
    if cadence == "weekly":
        return now - timedelta(days=7), now
    if cadence == "monthly":
        return now - timedelta(days=30), now
    return now - timedelta(days=7), now


def build_report_payload(db: Session, org: Organization, start: datetime, end: datetime) -> dict:
    rows = (
        db.query(UsageLedger)
        .filter(UsageLedger.org_id == org.id,
                UsageLedger.created_at >= start,
                UsageLedger.created_at < end)
        .order_by(UsageLedger.created_at.asc())
        .all()
    )
    total_in = sum(r.input_tokens for r in rows)
    total_out = sum(r.output_tokens for r in rows)
    total_cost = sum(r.total_cost for r in rows)
    success_count = sum(1 for r in rows if r.success)

    by_client: dict[int, dict] = {}
    for r in rows:
        s = by_client.setdefault(r.client_id, {
            "client_id": r.client_id, "requests": 0, "input_tokens": 0,
            "output_tokens": 0, "cost": 0.0, "errors": 0,
        })
        s["requests"] += 1
        s["input_tokens"] += r.input_tokens
        s["output_tokens"] += r.output_tokens
        s["cost"] += r.total_cost
        if not r.success:
            s["errors"] += 1

    return {
        "org_id": org.id,
        "org_name": org.name,
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "totals": {
            "requests": len(rows),
            "successful": success_count,
            "input_tokens": total_in,
            "output_tokens": total_out,
            "total_cost": total_cost,
        },
        "by_client": list(by_client.values()),
    }


def run_scheduled_reports(db: Session) -> int:
    if not settings.REPORT_SCHEDULE_ENABLED:
        return 0
    jobs = db.query(ScheduledReport).filter(ScheduledReport.is_active == True).all()
    sent = 0
    for job in jobs:
        org = db.query(Organization).filter(Organization.id == job.org_id).first()
        if not org:
            continue
        start, end = _date_range(job.cadence)
        report = build_report_payload(db, org, start, end)
        body_json = json.dumps(report, indent=2).encode("utf-8")
        body_csv = _to_csv(report)

        if job.target == "webhook" and job.target_url:
            try:
                import hmac, hashlib
                sig = hmac.new(settings.REPORT_WEBHOOK_SECRET.encode(), body_json, hashlib.sha256).hexdigest()
                with httpx.Client(timeout=10.0) as http:
                    r = http.post(
                        job.target_url,
                        content=body_json,
                        headers={"Content-Type": "application/json",
                                 "X-DyerGate-Report": job.cadence,
                                 "X-DyerGate-Signature": f"sha256={sig}"},
                    )
                sent += 1 if r.status_code < 300 else 0
            except Exception:
                logger.exception("report webhook failed: org=%s", org.id)
        elif job.target == "s3" and settings.REPORT_S3_ENABLED:
            try:
                s3 = _get_s3()
                key = f"reports/{org.slug}/{job.cadence}/{end:%Y/%m/%d}/report.json"
                s3.put_object(Bucket=settings.ARCHIVE_S3_BUCKET, Key=key, Body=body_json)
                csv_key = key.replace(".json", ".csv")
                s3.put_object(Bucket=settings.ARCHIVE_S3_BUCKET, Key=csv_key, Body=body_csv.encode("utf-8"))
                sent += 1
            except Exception:
                logger.exception("s3 report upload failed: org=%s", org.id)

        job.last_run_at = datetime.utcnow()
    db.commit()
    return sent


def _to_csv(report: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["client_id", "requests", "input_tokens", "output_tokens", "cost", "errors"])
    for c in report["by_client"]:
        w.writerow([c["client_id"], c["requests"], c["input_tokens"], c["output_tokens"], c["cost"], c["errors"]])
    return buf.getvalue()
