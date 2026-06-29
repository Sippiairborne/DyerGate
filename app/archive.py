import io
import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.models import UsageLedger

logger = logging.getLogger("dyergate.archive")


def _get_s3():
    import boto3
    kwargs = {
        "aws_access_key_id": settings.ARCHIVE_S3_ACCESS_KEY or None,
        "aws_secret_access_key": settings.ARCHIVE_S3_SECRET_KEY or None,
        "region_name": settings.ARCHIVE_S3_REGION,
    }
    if settings.ARCHIVE_S3_ENDPOINT:
        kwargs["endpoint_url"] = settings.ARCHIVE_S3_ENDPOINT
    return boto3.client("s3", **{k: v for k, v in kwargs.items() if v})


def archive_old_ledger(db: Session, days: Optional[int] = None) -> int:
    if not settings.ARCHIVE_ENABLED:
        return 0
    days = days or settings.ARCHIVE_AFTER_DAYS
    cutoff = datetime.utcnow() - timedelta(days=days)

    rows = (
        db.query(UsageLedger)
        .filter(UsageLedger.archived_at.is_(None), UsageLedger.created_at < cutoff)
        .order_by(UsageLedger.created_at.asc())
        .limit(5000)
        .all()
    )
    if not rows:
        return 0

    payload = [{
        "id": r.id, "org_id": r.org_id, "client_id": r.client_id,
        "endpoint": r.endpoint, "model": r.model,
        "input_tokens": r.input_tokens, "output_tokens": r.output_tokens,
        "total_cost": r.total_cost, "success": r.success,
        "upstream_status": r.upstream_status,
        "created_at": r.created_at.isoformat(),
    } for r in rows]

    body = (json.dumps(payload) + "\n").encode("utf-8")
    key = f"ledger-archive/{datetime.utcnow():%Y/%m/%d}/usage_{cutoff:%Y%m%d}_{rows[0].id}_{rows[-1].id}.json"

    try:
        s3 = _get_s3()
        s3.put_object(
            Bucket=settings.ARCHIVE_S3_BUCKET,
            Key=key,
            Body=body,
            ContentType="application/x-ndjson",
        )
        now = datetime.utcnow()
        for r in rows:
            r.archived_at = now
        db.commit()
        logger.info("Archived %d ledger rows to s3://%s/%s", len(rows), settings.ARCHIVE_S3_BUCKET, key)
        return len(rows)
    except Exception:
        db.rollback()
        logger.exception("archive upload failed")
        return 0
