import logging
import secrets
from datetime import datetime, timedelta

from fastapi import HTTPException, Request, Response, Depends, Cookie, Header
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    SaasCustomer, SaasSession, EmailVerification, PasswordReset,
    Organization,
)
from app.auth import hash_key, hash_password, verify_password

logger = logging.getLogger("dyergate.saas_auth")
SAAS_SESSION_COOKIE = "dg_customer"


def generate_verification_token() -> str:
    return secrets.token_urlsafe(48)


def signup(db: Session, email: str, password: str, org_name: str, org_slug: str) -> dict:
    if db.query(SaasCustomer).filter(SaasCustomer.email == email).first():
        raise HTTPException(status_code=409, detail="Email already registered.")
    if db.query(Organization).filter(Organization.slug == org_slug).first():
        raise HTTPException(status_code=409, detail="Org slug taken.")

    cust = SaasCustomer(
        email=email, password_hash=hash_password(password),
        is_active=True, email_verified_at=None,
    )
    db.add(cust); db.commit(); db.refresh(cust)

    org = Organization(name=org_name, slug=org_slug, quota_usd=1000.0, is_active=True)
    db.add(org); db.commit(); db.refresh(org)

    token = generate_verification_token()
    db.add(EmailVerification(
        customer_id=cust.id,
        token=hash_key(token),
        expires_at=datetime.utcnow() + timedelta(days=7),
    ))
    db.commit()
    return {"customer_id": cust.id, "org_id": org.id, "verify_token": token}


def verify_email(db: Session, token: str) -> bool:
    h = hash_key(token)
    ev = db.query(EmailVerification).filter(EmailVerification.token == h).first()
    if not ev or ev.consumed_at or ev.expires_at < datetime.utcnow():
        return False
    ev.consumed_at = datetime.utcnow()
    cust = db.query(SaasCustomer).filter(SaasCustomer.id == ev.customer_id).first()
    if cust:
        cust.email_verified_at = datetime.utcnow()
    db.commit()
    return True


def login(db: Session, email: str, password: str) -> tuple[str, datetime, SaasCustomer]:
    cust = db.query(SaasCustomer).filter(SaasCustomer.email == email, SaasCustomer.is_active == True).first()
    if not cust or not verify_password(password, cust.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials.")
    token = secrets.token_urlsafe(48)
    expires = datetime.utcnow() + timedelta(days=7)
    sess = SaasSession(customer_id=cust.id, token_hash=hash_key(token), expires_at=expires)
    db.add(sess)
    cust.last_login_at = datetime.utcnow()
    db.commit()
    return token, expires, cust


def current_customer(
    request: Request,
    db: Session = Depends(get_db),
    cookie: str | None = Cookie(default=None, alias=SAAS_SESSION_COOKIE),
) -> SaasCustomer:
    if not cookie:
        raise HTTPException(status_code=401, detail="Sign in required.")
    sess = db.query(SaasSession).filter(SaasSession.token_hash == hash_key(cookie)).first()
    if not sess or sess.expires_at < datetime.utcnow():
        raise HTTPException(status_code=401, detail="Session expired.")
    cust = db.query(SaasCustomer).filter(SaasCustomer.id == sess.customer_id, SaasCustomer.is_active == True).first()
    if not cust:
        raise HTTPException(status_code=401, detail="Customer disabled.")
    request.state.customer = cust
    return cust


def request_password_reset(db: Session, email: str) -> str:
    cust = db.query(SaasCustomer).filter(SaasCustomer.email == email).first()
    if not cust:
        # Do not reveal existence
        return ""
    token = secrets.token_urlsafe(48)
    db.add(PasswordReset(customer_id=cust.id, token=hash_key(token),
                         expires_at=datetime.utcnow() + timedelta(hours=2)))
    db.commit()
    return token


def perform_password_reset(db: Session, token: str, new_password: str) -> bool:
    h = hash_key(token)
    pr = db.query(PasswordReset).filter(PasswordReset.token == h).first()
    if not pr or pr.consumed_at or pr.expires_at < datetime.utcnow():
        return False
    cust = db.query(SaasCustomer).filter(SaasCustomer.id == pr.customer_id).first()
    if not cust:
        return False
    cust.password_hash = hash_password(new_password)
    pr.consumed_at = datetime.utcnow()
    db.commit()
    return True
