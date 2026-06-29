import base64
import logging
import secrets
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.auth import hash_password, create_session, hash_key
from app.models import SsoConfig, SsoUserLink, AdminUser, Organization, OrgMember

logger = logging.getLogger("dyergate.sso")


# ---------- OIDC ----------

async def oidc_discovery(issuer: str) -> dict:
    """Fetch .well-known/openid-configuration."""
    url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    if not url.startswith("http"):
        url = "https://" + url
    async with httpx.AsyncClient(timeout=10.0) as http:
        r = await http.get(url)
    r.raise_for_status()
    return r.json()


async def oidc_authorize_url(config: SsoConfig, state: str, redirect_uri: str) -> str:
    """Build the OIDC authorize URL."""
    discovery = await oidc_discovery(config.issuer)
    params = {
        "response_type": "code",
        "client_id": config.client_id,
        "redirect_uri": redirect_uri,
        "scope": "openid email profile",
        "state": state,
    }
    return f"{discovery['authorization_endpoint']}?{urlencode(params)}"


async def oidc_exchange_code(config: SsoConfig, code: str, redirect_uri: str) -> dict:
    """Exchange auth code for tokens."""
    discovery = await oidc_discovery(config.issuer)
    async with httpx.AsyncClient(timeout=10.0) as http:
        r = await http.post(discovery["token_endpoint"], data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": config.client_id,
            "client_secret": config.client_secret,
        })
    r.raise_for_status()
    return r.json()


async def oidc_fetch_userinfo(config: SsoConfig, access_token: str) -> dict:
    discovery = await oidc_discovery(config.issuer)
    async with httpx.AsyncClient(timeout=10.0) as http:
        r = await http.get(discovery["userinfo_endpoint"],
                           headers={"Authorization": f"Bearer {access_token}"})
    r.raise_for_status()
    return r.json()


# ---------- SAML ----------

def _b64decode(data: str) -> bytes:
    try:
        return base64.b64decode(data)
    except Exception:
        return base64.b64decode(data + "=" * (-len(data) % 4))


async def saml_build_auth_request(config: SsoConfig, state: str) -> str:
    """Build a SAML AuthnRequest and return the redirect URL."""
    try:
        from onelogin.saml2.auth import OneLogin_Saml2_Auth
        from onelogin.saml2.settings import OneLogin_Saml2_Settings
    except ImportError:
        raise HTTPException(status_code=501, detail="SAML support not installed.")

    settings = OneLogin_Saml2_Settings({
        "sp": {
            "entityId": config.entity_id or "dyergate",
            "assertionConsumerService": {"url": "", "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"},
        },
        "idp": {
            "entityId": config.issuer,
            "singleSignOnService": {"url": config.sso_url, "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"},
            "x509cert": config.certificate or "",
        },
    }, sp_validation_only=True)
    auth = OneLogin_Saml2_Auth({"https": "on", "http_host": "localhost"}, settings)
    return auth.login(return_to=state)


def saml_process_response(config: SsoConfig, saml_response_b64: str) -> dict:
    """Parse a SAML response and return {subject, email, attributes}."""
    try:
        from onelogin.saml2.response import OneLogin_Saml2_Response
        from onelogin.saml2.settings import OneLogin_Saml2_Settings
    except ImportError:
        raise HTTPException(status_code=501, detail="SAML support not installed.")

    settings = OneLogin_Saml2_Settings({
        "sp": {"entityId": config.entity_id or "dyergate",
               "assertionConsumerService": {"url": "", "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"}},
        "idp": {"entityId": config.issuer,
                "singleSignOnService": {"url": config.sso_url, "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"},
                "x509cert": config.certificate or ""},
    }, sp_validation_only=True)
    response = OneLogin_Saml2_Response(settings, _b64decode(saml_response_b64))
    if not response.is_valid({}):
        raise HTTPException(status_code=401, detail="Invalid SAML response.")
    return {
        "subject": response.get_nameid(),
        "email": (response.get_attributes().get("email") or [None])[0],
        "attributes": response.get_attributes(),
    }


# ---------- JIT user provisioning ----------

def provision_or_link_sso_user(db: Session, config: SsoConfig, subject: str, email: str) -> AdminUser:
    """Find or create an admin user; bind to the org with the configured role."""
    link = db.query(SsoUserLink).filter(
        SsoUserLink.org_id == config.org_id, SsoUserLink.subject == subject
    ).first()

    if link:
        link.last_login_at = datetime.utcnow()
        link.email = email or link.email
        user = db.query(AdminUser).filter(AdminUser.id == link.user_id).first()
        db.commit()
        if user:
            return user

    # JIT: find by email OR create a new admin user
    user = None
    if email:
        user = db.query(AdminUser).filter(AdminUser.email == email).first()
    if not user:
        if not email:
            raise HTTPException(status_code=400, detail="SSO response missing email.")
        user = AdminUser(
            email=email,
            password_hash=hash_password(secrets.token_urlsafe(32)),
            is_active=True,
            is_superadmin=False,
        )
        db.add(user); db.commit(); db.refresh(user)

    # Bind user to org
    if not db.query(OrgMember).filter(OrgMember.user_id == user.id, OrgMember.org_id == config.org_id).first():
        db.add(OrgMember(user_id=user.id, org_id=config.org_id, role=config.default_role))
    db.add(SsoUserLink(org_id=config.org_id, user_id=user.id, subject=subject, email=email))
    db.commit()
    return user
