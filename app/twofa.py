import base64
import io
import logging
from typing import Optional

import pyotp
import qrcode
from sqlalchemy.orm import Session

from app.models import AdminUser
from app.auth import hash_password

logger = logging.getLogger("dyergate.twofa")


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(user: AdminUser, secret: str) -> str:
    return pyotp.totp.TOTP(secret).provisioning_uri(
        name=user.email, issuer_name="DyerGate"
    )


def qr_code_data_url(uri: str) -> str:
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def verify_totp(secret: str, code: str) -> bool:
    if not secret or not code:
        return False
    return pyotp.TOTP(secret).verify(code, valid_window=1)


def enable_2fa(db: Session, user: AdminUser) -> dict:
    """Generate a new TOTP secret and store its hash. Returns provisioning URI + QR."""
    secret = generate_totp_secret()
    user.totp_secret = secret
    user.totp_enabled = True
    db.commit()
    uri = provisioning_uri(user, secret)
    return {
        "secret": secret,
        "provisioning_uri": uri,
        "qr_code_data_url": qr_code_data_url(uri),
    }


def disable_2fa(db: Session, user: AdminUser) -> None:
    user.totp_secret = None
    user.totp_enabled = False
    db.commit()
