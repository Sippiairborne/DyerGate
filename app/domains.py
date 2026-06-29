import logging
import secrets
from datetime import datetime

from sqlalchemy.orm import Session
from fastapi import Request

from app.models import Organization, CustomDomain

logger = logging.getLogger("dyergate.domains")


def resolve_org_by_host(request: Request, db: Session) -> Organization | None:
    """
    Resolve an org from the Host header.
    Order: custom verified domain → subdomain slug → None.
    """
    host = request.headers.get("host", "").lower().split(":")[0]
    if not host:
        return None

    # Custom domain
    cd = db.query(CustomDomain).filter(
        CustomDomain.domain == host, CustomDomain.verified_at.isnot(None)
    ).first()
    if cd:
        return db.query(Organization).filter(Organization.id == cd.org_id).first()

    # Subdomain: <slug>.dyergate.cloud
    parts = host.split(".")
    if len(parts) >= 3:
        slug = parts[0]
        org = db.query(Organization).filter(Organization.slug == slug, Organization.is_active == True).first()
        return org
    return None


def add_custom_domain(db: Session, org: Organization, domain: str) -> CustomDomain:
    if db.query(CustomDomain).filter(CustomDomain.domain == domain).first():
        from fastapi import HTTPException
        raise HTTPException(status_code=409, detail="Domain already in use.")
    token = secrets.token_urlsafe(24)
    cd = CustomDomain(org_id=org.id, domain=domain, verification_token=token,
                     ssl_status="pending", is_primary=False)
    db.add(cd); db.commit(); db.refresh(cd)
    return cd


def verify_custom_domain(db: Session, domain: str) -> bool:
    """Verify via DNS TXT record. Caller checks the TXT externally."""
    cd = db.query(CustomDomain).filter(CustomDomain.domain == domain).first()
    if not cd:
        return False
    cd.verified_at = datetime.utcnow()
    cd.ssl_status = "provisioning"
    db.commit()
    return True
