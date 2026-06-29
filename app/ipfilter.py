import ipaddress
import logging
from typing import Optional

from fastapi import Request, HTTPException
from sqlalchemy.orm import Session

from app.models import IpAllowlist

logger = logging.getLogger("dyergate.ipfilter")


def _resolve_client_ip(request: Request) -> str:
    fwd = request.headers.get("X-Forwarded-For")
    if fwd:
        return fwd.split(",")[0].strip()
    real = request.headers.get("X-Real-IP")
    if real:
        return real.strip()
    return request.client.host if request.client else "0.0.0.0"


def _matches(cidr: str, ip: str) -> bool:
    try:
        if "/" in cidr:
            return ipaddress.ip_address(ip) in ipaddress.ip_network(cidr, strict=False)
        return ipaddress.ip_address(ip) == ipaddress.ip_address(cidr)
    except ValueError:
        return False


def check_admin_ip(request: Request, db: Session, allow_when_empty: bool = True) -> None:
    """If any allowlist entries exist, enforce them for admin requests."""
    count = db.query(IpAllowlist).filter(IpAllowlist.is_active == True).count()
    if count == 0:
        if allow_when_empty:
            return
        raise HTTPException(status_code=403, detail="No IP allowlist configured.")
    ip = _resolve_client_ip(request)
    rows = db.query(IpAllowlist).filter(IpAllowlist.is_active == True).all()
    for row in rows:
        if _matches(row.cidr, ip):
            return
    logger.warning("Admin request from blocked IP: %s", ip)
    raise HTTPException(status_code=403, detail=f"IP {ip} not allowed.")
