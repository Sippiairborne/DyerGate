import hashlib
from app.auth import hash_key, generate_api_key


def test_key_format():
    raw, h, prefix = generate_api_key()
    assert raw.startswith("dg_")
    assert len(prefix) == 8
    assert hash_key(raw) == h


def test_invalid_prefix_rejected(client):
    r = client.post("/v1/chat/completions",
                    headers={"X-DyerGate-Key": "bogus_xxxx"},
                    json={"messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 401


def test_valid_key_accepted(client, db):
    from app.models import Organization, AccountTier, ClientAccount, ApiKey

    org = Organization(name="Acme", slug="acme", quota_usd=100, is_active=True)
    db.add(org); db.commit(); db.refresh(org)
    tier = AccountTier(name="standard", rate_limit_per_min=60,
                       cost_per_thousand_input=0.002, cost_per_thousand_output=0.003)
    db.add(tier); db.commit(); db.refresh(tier)
    raw, h, prefix = generate_api_key()
    c = ClientAccount(org_id=org.id, client_identity="alpha",
                      tier_id=tier.id, credit_balance=10.0, is_active=True)
    db.add(c); db.commit(); db.refresh(c)
    db.add(ApiKey(client_id=c.id, key_hash=h, key_prefix=prefix)); db.commit()

    # Mock upstream is unavailable in tests; we only care the key is accepted (4xx/5xx from upstream, not 401)
    r = client.post("/v1/chat/completions",
                    headers={"X-DyerGate-Key": raw},
                    json={"model": "x", "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code != 401
