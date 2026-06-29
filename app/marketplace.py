import logging
import time
from datetime import datetime
from typing import Any

import httpx
from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    AgentSkill, AgentInvocation, ClientAccount, Organization,
    StripeConnectAccount,
)
from app.metering import tokens, compute_cost
from app.billing_saas import stripe

logger = logging.getLogger("dyergate.marketplace")


async def invoke_skill(
    db: Session,
    client: ClientAccount,
    skill_slug: str,
    payload: dict,
    request_id: str | None = None,
) -> dict:
    skill = db.query(AgentSkill).filter(
        AgentSkill.slug == skill_slug,
        AgentSkill.is_approved == True,
        AgentSkill.is_active == True,
    ).first()
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_slug}' not found.")

    # Validate payload against schema (lightweight — required keys present)
    schema = skill.parameters_schema or {}
    required = schema.get("required", [])
    missing = [k for k in required if k not in payload]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing required parameters: {missing}")

    # Forward to the skill's upstream endpoint
    headers = {"Content-Type": "application/json"}
    if skill.auth_header:
        headers["Authorization"] = skill.auth_header
    start = time.time()
    success = False
    response_obj: Any = {}
    error_msg = None
    upstream_status = None
    try:
        async with httpx.AsyncClient(timeout=60.0) as http:
            r = await http.post(skill.endpoint_url, json=payload, headers=headers)
            upstream_status = r.status_code
            if 200 <= r.status_code < 300:
                try:
                    response_obj = r.json()
                except Exception:
                    response_obj = {"raw": r.text}
                success = True
            else:
                error_msg = f"upstream_status_{r.status_code}: {r.text[:500]}"
    except Exception as e:
        error_msg = str(e)

    latency_ms = int((time.time() - start) * 1000)
    cost = skill.cost_per_invocation

    # Deduct from caller (use same reserve/refund pattern: here single-shot, no streaming)
    if success and cost > 0:
        if client.credit_balance < cost:
            raise HTTPException(status_code=402, detail=f"Insufficient credit for skill (need {cost:.4f}).")
        client.credit_balance -= cost

    # Marketplace revenue share: if skill provider has Stripe Connect, push a transfer
    if success and settings.STRIPE_CONNECT_ENABLED:
        provider_org = db.query(Organization).filter(Organization.id == skill.provider_org_id).first()
        provider_connect = db.query(StripeConnectAccount).filter(
            StripeConnectAccount.org_id == skill.provider_org_id,
            StripeConnectAccount.charges_enabled == True,
        ).first()
        if provider_connect and provider_org and settings.STRIPE_SECRET_KEY:
            try:
                # The platform takes AGENT_REVENUE_SHARE_BPS, rest goes to provider.
                amount_cents = int(cost * 100 * 100)  # assume 1 credit = $1 = 100 cents
                platform_fee = int(amount_cents * settings.AGENT_REVENUE_SHARE_BPS / 10000)
                stripe.Transfer.create(
                    amount=amount_cents - platform_fee,
                    currency="usd",
                    destination=provider_connect.stripe_account_id,
                    metadata={"dyergate_skill_id": str(skill.id), "dyergate_caller_org": str(client.org_id)},
                )
            except Exception as e:
                logger.exception("marketplace transfer failed: %s", e)

    # Record the invocation
    inv = AgentInvocation(
        org_id=client.org_id,
        caller_client_id=client.id,
        skill_id=skill.id,
        skill_slug=skill.slug,
        request_payload=payload,
        response_payload=response_obj if isinstance(response_obj, dict) else {"result": str(response_obj)[:4000]},
        latency_ms=latency_ms,
        cost=cost if success else 0.0,
        success=success,
        error=error_msg,
        upstream_status=upstream_status,
        request_id=request_id,
    )
    db.add(inv); db.commit()
    if not success:
        raise HTTPException(status_code=502, detail=f"Skill execution failed: {error_msg}")
    return response_obj
