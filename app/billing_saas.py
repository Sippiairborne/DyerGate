import logging
import secrets
from datetime import datetime
from typing import Optional

import stripe
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    Organization, ClientAccount, Subscription,
    StripeConnectAccount, UsageMeteringEvent, Payment, CreditPackage,
)
from app.webhooks import fire_event

logger = logging.getLogger("dyergate.billing_saas")
stripe.api_key = settings.STRIPE_SECRET_KEY


# ---------- Plans (configured in Stripe dashboard) ----------

PLAN_PRESETS = {
    "free":       {"included_credits": 2.0,    "monthly_fee_cents": 0},
    "starter":    {"included_credits": 25.0,   "monthly_fee_cents": 2900},   # $29/mo
    "growth":     {"included_credits": 100.0,  "monthly_fee_cents": 9900},   # $99/mo
    "business":   {"included_credits": 500.0,  "monthly_fee_cents": 49900},  # $499/mo
    "enterprise": {"included_credits": 5000.0, "monthly_fee_cents": 0},      # custom
}


def ensure_stripe_ready() -> None:
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(status_code=503, detail="Stripe not configured.")


def create_connect_onboarding(db: Session, org: Organization, return_url: str, refresh_url: str) -> str:
    """Create a Stripe Connect Express account and return the onboarding URL."""
    ensure_stripe_ready()
    existing = db.query(StripeConnectAccount).filter(StripeConnectAccount.org_id == org.id).first()
    if existing and existing.details_submitted and existing.charges_enabled:
        return existing.onboarding_url or ""

    if not existing:
        acct = stripe.Account.create(
            type="express",
            metadata={"dyergate_org_id": str(org.id), "dyergate_org_slug": org.slug},
        )
        existing = StripeConnectAccount(
            org_id=org.id, stripe_account_id=acct.id,
            charges_enabled=False, payouts_enabled=False, details_submitted=False,
        )
        db.add(existing); db.commit(); db.refresh(existing)

    link = stripe.AccountLink.create(
        account=existing.stripe_account_id,
        refresh_url=refresh_url,
        return_url=return_url,
        type="account_onboarding",
    )
    existing.onboarding_url = link.url
    db.commit()
    return link.url


def sync_connect_status(db: Session, account_id: str) -> Optional[StripeConnectAccount]:
    if not settings.STRIPE_SECRET_KEY:
        return None
    acct = stripe.Account.retrieve(account_id)
    row = db.query(StripeConnectAccount).filter(StripeConnectAccount.stripe_account_id == account_id).first()
    if not row:
        return None
    row.charges_enabled = bool(acct.get("charges_enabled"))
    row.payouts_enabled = bool(acct.get("payouts_enabled"))
    row.details_submitted = bool(acct.get("details_submitted"))
    db.commit()
    return row


def create_subscription(
    db: Session, org: Organization, plan_name: str,
    stripe_customer_id: str, stripe_price_id: str,
) -> Subscription:
    ensure_stripe_ready()
    preset = PLAN_PRESETS.get(plan_name)
    if not preset:
        raise HTTPException(status_code=400, detail=f"Unknown plan: {plan_name}")

    sub = stripe.Subscription.create(
        customer=stripe_customer_id,
        items=[{"price": stripe_price_id}],
        payment_behavior="default_incomplete",
        payment_settings={"save_default_payment_method": "on_subscription"},
        expand=["latest_invoice.payment_intent"],
        metadata={"dyergate_org_id": str(org.id)},
    )
    row = Subscription(
        org_id=org.id,
        plan_name=plan_name,
        stripe_subscription_id=sub.id,
        stripe_price_id=stripe_price_id,
        status=sub.status,
        current_period_start=datetime.utcfromtimestamp(sub.current_period_start),
        current_period_end=datetime.utcfromtimestamp(sub.current_period_end),
        included_credits=preset["included_credits"],
    )
    db.add(row); db.commit(); db.refresh(row)
    return row


def report_metered_usage(
    db: Session, org_id: int, subscription_id: int,
    stripe_subscription_item_id: str, quantity: float,
    idempotency_key: Optional[str] = None,
) -> bool:
    """Push usage to Stripe for metered billing in subscription + overage model."""
    if not settings.STRIPE_SECRET_KEY:
        return False
    idem = idempotency_key or secrets.token_urlsafe(16)
    existing = db.query(UsageMeteringEvent).filter(UsageMeteringEvent.idempotency_key == idem).first()
    if existing:
        return True
    try:
        stripe.SubscriptionItem.create_usage_record(
            stripe_subscription_item_id,
            quantity=int(quantity),
            timestamp=int(datetime.utcnow().timestamp()),
            action="increment",
            idempotency_key=idem,
        )
        db.add(UsageMeteringEvent(
            org_id=org_id, subscription_id=subscription_id,
            stripe_subscription_item_id=stripe_subscription_item_id,
            quantity=quantity, idempotency_key=idem,
        ))
        db.commit()
        return True
    except Exception as e:
        logger.exception("metered usage report failed: %s", e)
        return False


def create_topup_with_connect(
    db: Session, client: ClientAccount, package: CreditPackage,
    success_url: str, cancel_url: str,
) -> dict:
    """
    Create a Checkout Session that uses the org's connected Stripe account
    (if marketplace mode is enabled) with a platform application fee.
    """
    ensure_stripe_ready()
    org_connect = db.query(StripeConnectAccount).filter(
        StripeConnectAccount.org_id == client.org_id,
        StripeConnectAccount.charges_enabled == True,
    ).first()

    checkout_kwargs = {
        "mode": "payment",
        "line_items": [{
            "price_data": {
                "currency": "usd",
                "product_data": {
                    "name": f"DyerGate Credits — {package.name}",
                    "description": f"{package.credit_amount:.2f} credits for {client.client_identity}",
                },
                "unit_amount": package.usd_cents,
            },
            "quantity": 1,
        }],
        "metadata": {
            "dyergate_org_id": str(client.org_id),
            "dyergate_client_id": str(client.id),
            "dyergate_credit_amount": str(package.credit_amount),
        },
        "success_url": success_url + "?session_id={CHECKOUT_SESSION_ID}",
        "cancel_url": cancel_url,
    }

    if settings.STRIPE_CONNECT_ENABLED and org_connect:
        checkout_kwargs["payment_intent_data"] = {
            "application_fee_amount": int(package.usd_cents * settings.PLATFORM_FEE_BPS / 10000),
            "transfer_data": {"destination": org_connect.stripe_account_id},
        }
        checkout_kwargs["stripe_account"] = org_connect.stripe_account_id

    checkout = stripe.checkout.Session.create(**checkout_kwargs)
    payment = Payment(
        org_id=client.org_id, client_id=client.id,
        stripe_session_id=checkout.id,
        package_name=package.name,
        usd_cents=package.usd_cents, credit_amount=package.credit_amount,
        status="pending", source="stripe_checkout",
    )
    db.add(payment); db.commit(); db.refresh(payment)
    return {"checkout_url": checkout.url, "session_id": checkout.id}
