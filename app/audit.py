import json
import logging
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models import AuditLog
from app.audit_stream import enqueue

logger = logging.getLogger("dyergate.audit")


def record_audit(db, actor, action, target_type=None, target_id=None,
                 details=None, ip_address=None, request_id=None) -> None:
    try:
        entry = AuditLog(
            actor=actor, action=action, target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            details=json.dumps(details)[:4000] if details else None,
            ip_address=ip_address, request_id=request_id,
        )
        db.add(entry); db.commit(); db.refresh(entry)
        enqueue(entry.id)
    except Exception:
        db.rollback()
        logger.exception("audit log write failed")
