import logging
from datetime import datetime
from typing import Optional

import stripe
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.models import ClientAccount, CreditPackage, Payment
from app.webhooks import fire_event

logger = logging.getLogger("dyergate.billing")
stripe.api_key = settings.STRIPE_SECRET_KEY


def ensure_stripe_ready() -> None:
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(status_code=503, detail="Stripe not configured.")


def list_packages_for_org(db: Session, org_id: int) -> list[CreditPackage]:
    return (
        db.query(CreditPackage)
        .filter(CreditPackage.is_active == True)
        .filter((CreditPackage.org_id == org_id) | (CreditPackage.org_id.is_(None)))
        .all()
    )


def create_topup_session(
    db: Session,
    client: ClientAccount,
    package_id: int,
    success_url: Optional[str] = None,
    cancel_url: Optional[str] = None,
) -> dict:
    ensure_stripe_ready()
    pkg = db.query(CreditPackage).filter(
        CreditPackage.id == package_id, CreditPackage.is_active == True
    ).first()
    if not pkg:
        raise HTTPException(status_code=404, detail="Credit package not found.")
    if pkg.org_id is not None and pkg.org_id != client.org_id:
        raise HTTPException(status_code=403, detail="Package not available for this org.")

    success_url = success_url or settings.STRIPE_SUCCESS_URL
    cancel_url = cancel_url or settings.STRIPE_CANCEL_URL

    checkout = stripe.checkout.Session.create(
        mode="payment",
        payment_method_types=["card"],
        line_items=[{
            "price_data": {
                "currency": "usd",
                "product_data": {
                    "name": f"DyerGate Credits — {pkg.name}",
                    "description": f"{pkg.credit_amount:.2f} credits for org {client.org_id}",
                },
                "unit_amount": pkg.usd_cents,
            },
            "quantity": 1,
        }],
        metadata={
            "dyergate_org_id": str(client.org_id),
            "dyergate_client_id": str(client.id),
            "dyergate_client_identity": client.client_identity,
            "dyergate_package_id": str(pkg.id),
            "dyergate_credit_amount": str(pkg.credit_amount),
        },
        success_url=success_url + "?session_id={CHECKOUT_SESSION_ID}",
        cancel_url=cancel_url,
    )

    payment = Payment(
        org_id=client.org_id,
        client_id=client.id,
        stripe_session_id=checkout.id,
        package_name=pkg.name,
        usd_cents=pkg.usd_cents,
        credit_amount=pkg.credit_amount,
        status="pending",
        source="stripe_checkout",
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return {"checkout_url": checkout.url, "session_id": checkout.id}


def handle_checkout_completed(session: dict, db: Session) -> None:
    sid = session.get("id")
    if not sid:
        return
    payment = db.query(Payment).filter(Payment.stripe_session_id == sid).first()
    if not payment:
        logger.warning("Stripe webhook for unknown session: %s", sid)
        return
    if payment.status == "paid":
        return

    payment.status = "paid"
    payment.stripe_payment_intent_id = session.get("payment_intent")
    payment.completed_at = datetime.utcnow()

    client = db.query(ClientAccount).filter(ClientAccount.id == payment.client_id).first()
    if client:
        client.credit_balance += payment.credit_amount
        db.commit()
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(fire_event(
                    db, client, "payment_succeeded",
                    {"credit_amount": payment.credit_amount, "client_identity": client.client_identity,
                     "org_id": client.org_id, "new_balance": client.credit_balance}
                ))
        except Exception:
            logger.exception("failed to schedule payment_succeeded event")
    else:
        db.commit()


def process_stripe_event(event: dict, db: Session) -> dict:
    etype = event.get("type")
    data = event.get("data", {}).get("object", {})
    if etype == "checkout.session.completed":
        handle_checkout_completed(data, db)
        return {"handled": True, "type": etype}
    if etype == "charge.refunded":
        logger.info("Refund event received: %s", data.get("id"))
        return {"handled": True, "type": etype}
    return {"handled": False, "type": etype}
