import json
import hmac
import hashlib


def _sign(payload: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def test_valid_signature_passes(client, monkeypatch):
    # Configure webhook secret
    from app.config import settings
    monkeypatch.setattr(settings, "STRIPE_WEBHOOK_SECRET", "whsec_test_1234567890")
    payload = json.dumps({"type": "checkout.session.completed",
                          "data": {"object": {"id": "cs_test_x",
                                              "metadata": {},
                                              "payment_intent": "pi_1"}}}).encode()
    sig = _sign(payload, "whsec_test_1234567890")
    r = client.post("/admin/stripe/webhook",
                    content=payload,
                    headers={"stripe-signature": sig,
                             "Content-Type": "application/json"})
    assert r.status_code == 200
    assert r.json()["handled"] is True


def test_invalid_signature_rejected(client, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "STRIPE_WEBHOOK_SECRET", "whsec_test_1234567890")
    r = client.post("/admin/stripe/webhook",
                    content=b'{"type":"x"}',
                    headers={"stripe-signature": "bad"})
    assert r.status_code == 400
