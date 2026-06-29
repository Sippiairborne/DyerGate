import io
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from threading import Lock

import boto3

from app.config import settings
from app.database import SessionLocal
from app.models import AuditLog, AuditEventQueue

logger = logging.getLogger("dyergate.audit_stream")
_buffer_lock = Lock()
_buffer: list[dict] = []
_last_flush = time.time()
_FLUSH_INTERVAL = 5.0
_MAX_BATCH = 500


def _s3_client():
    kwargs = {
        "aws_access_key_id": settings.ARCHIVE_S3_ACCESS_KEY or None,
        "aws_secret_access_key": settings.ARCHIVE_S3_SECRET_KEY or None,
        "region_name": settings.ARCHIVE_S3_REGION,
    }
    if settings.ARCHIVE_S3_ENDPOINT:
        kwargs["endpoint_url"] = settings.ARCHIVE_S3_ENDPOINT
    return boto3.client("s3", **{k: v for k, v in kwargs.items() if v})


def enqueue(audit_log_id: int) -> None:
    if not settings.AUDIT_STREAM_ENABLED:
        return
    db = SessionLocal()
    try:
        db.add(AuditEventQueue(audit_log_id=audit_log_id))
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def flush_now() -> int:
    """Called periodically. Uploads buffered events to S3 as NDJSON, marks delivered."""
    if not settings.AUDIT_STREAM_ENABLED:
        return 0
    db = SessionLocal()
    sent = 0
    try:
        pending = db.query(AuditEventQueue).filter(
            AuditEventQueue.delivered_to_s3 == False
        ).limit(_MAX_BATCH).all()
        if not pending:
            return 0

        ids = [p.audit_log_id for p in pending]
        logs = db.query(AuditLog).filter(AuditLog.id.in_(ids)).all()
        log_by_id = {l.id: l for l in logs}

        body = io.BytesIO()
        for p in pending:
            l = log_by_id.get(p.audit_log_id)
            if not l:
                p.delivered_to_s3 = True
                continue
            event = {
                "id": l.id, "actor": l.actor, "action": l.action,
                "target_type": l.target_type, "target_id": l.target_id,
                "details": json.loads(l.details) if l.details else None,
                "ip_address": l.ip_address, "request_id": l.request_id,
                "org_id": l.org_id, "created_at": l.created_at.isoformat(),
            }
            body.write((json.dumps(event) + "\n").encode())
            p.delivered_to_s3 = True
            sent += 1

        try:
            s3 = _s3_client()
            key = f"{settings.AUDIT_STREAM_S3_PREFIX}{datetime.utcnow():%Y/%m/%d/%H%M%S}_audit.ndjson"
            s3.put_object(
                Bucket=settings.AUDIT_STREAM_S3_BUCKET,
                Key=key,
                Body=body.getvalue(),
                ContentType="application/x-ndjson",
            )
        except Exception as e:
            logger.exception("audit stream S3 upload failed: %s", e)
            for p in pending:
                p.delivered_to_s3 = False
        db.commit()
    finally:
        db.close()
    return sent


def start_audit_flusher(scheduler) -> None:
    from apscheduler.triggers.interval import IntervalTrigger
    scheduler.add_job(
        flush_now, IntervalTrigger(seconds=_FLUSH_INTERVAL),
        id="audit_stream", replace_existing=True, max_instances=1, coalesce=True,
    )
