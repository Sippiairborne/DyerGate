import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Header, Depends, HTTPException, Request, Response, status, Cookie
from passlib.hash import bcrypt
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import ClientAccount, ApiKey, AdminUser, AdminSession, OrgMember
from app.audit import record_audit

logger = logging.getLogger("dyergate.auth")

CLIENT_HEADER = "X-DyerGate-Key"
KEY_PREFIX = "dg_"
SESSION_COOKIE = "dg_session"


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_api_key() -> tuple[str, str, str]:
    prefix = secrets.token_hex(4)
    raw = f"{KEY_PREFIX}{prefix}_{secrets.token_urlsafe(32)}"
    return raw, hash_key(raw), prefix


def _extract_bearer(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    if value.lower().startswith("bearer "):
        return value[7:].strip()
    return value.strip() or None


def _resolve_admin_user(request: Request, db: Session, session_token: Optional[str]) -> Optional[AdminUser]:
    if not session_token:
        return None
    token_hash = hash_key(session_token)
    sess = db.query(AdminSession).filter(AdminSession.token_hash == token_hash).first()
    if not sess or sess.expires_at < datetime.utcnow():
        return None
    user = db.query(AdminUser).filter(AdminUser.id == sess.user_id, AdminUser.is_active == True).first()
    if user:
        request.state.actor = f"user:{user.email}"
        request.state.admin_user = user
    return user


def verify_client(
    request: Request,
    x_dyergate_key: Optional[str] = Header(default=None, alias=CLIENT_HEADER),
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> ClientAccount:
    raw = x_dyergate_key or _extract_bearer(authorization) or ""
    if not raw.startswith(KEY_PREFIX):
        raise HTTPException(status_code=401, detail="Invalid API key format.")

    key_hash = hash_key(raw)
    now = datetime.utcnow()
    key_row = db.query(ApiKey).filter(ApiKey.key_hash == key_hash).first()
    if not key_row:
        hmac.compare_digest(key_hash, "0" * 64)
        raise HTTPException(status_code=401, detail="Invalid API key.")

    if key_row.revoked_at is not None and (key_row.expires_at is None or key_row.expires_at < now):
        raise HTTPException(status_code=401, detail="API key revoked.")

    if key_row.expires_at is not None and key_row.expires_at < now:
        raise HTTPException(status_code=401, detail="API key expired.")

    client = db.query(ClientAccount).filter(ClientAccount.id == key_row.client_id).first()
    if not client or not client.is_active:
        raise HTTPException(status_code=401, detail="Client disabled.")
    if client.credit_balance <= 0:
        raise HTTPException(status_code=402, detail="Insufficient credit balance.")

    request.state.client_id = client.id
    request.state.org_id = client.org_id
    request.state.client_identity = client.client_identity
    request.state.api_key_prefix = key_row.key_prefix
    return client


def require_admin(
    request: Request,
    db: Session = Depends(get_db),
    dg_session: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE),
    x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
) -> AdminUser:
    # Two ways in: legacy shared ADMIN_API_KEY (bootstrap) OR a session cookie.
    user = _resolve_admin_user(request, db, dg_session)
    if user:
        return user

    if x_admin_key:
        expected = settings.ADMIN_API_KEY
        if expected and len(expected) >= 16 and hmac.compare_digest(x_admin_key.encode(), expected.encode()):
            request.state.actor = "admin:legacy"
            # Synthetic superadmin for backwards compatibility
            sb = AdminUser(id=0, email="legacy@bootstrap", is_active=True, is_superadmin=True)
            request.state.admin_user = sb
            return sb

    raise HTTPException(status_code=401, detail="Admin authentication required.")


def require_role(*roles: str):
    """Dependency factory: enforce role within the org specified in path/query."""
    def _check(
        request: Request,
        db: Session = Depends(get_db),
        user: AdminUser = Depends(require_admin),
    ) -> AdminUser:
        if user.is_superadmin:
            return user
        # org_id must be set somewhere (path param or query); we read from request.state
        org_id = getattr(request.state, "org_id", None)
        if org_id is None:
            raise HTTPException(status_code=400, detail="org_id required for this operation.")
        m = db.query(OrgMember).filter(
            OrgMember.user_id == user.id, OrgMember.org_id == org_id
        ).first()
        if not m or m.role not in roles:
            raise HTTPException(status_code=403, detail=f"Requires role(s): {roles}")
        request.state.member = m
        return user
    return _check


# ---------- Admin auth helpers ----------

def hash_password(plain: str) -> str:
    return bcrypt.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.verify(plain, hashed)
    except Exception:
        return False


def create_session(db: Session, user: AdminUser, ttl_hours: int = 24) -> tuple[str, datetime]:
    token = secrets.token_urlsafe(48)
    expires = datetime.utcnow() + timedelta(hours=ttl_hours)
    sess = AdminSession(user_id=user.id, token_hash=hash_key(token), expires_at=expires)
    db.add(sess)
    db.commit()
    return token, expires
