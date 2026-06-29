from datetime import datetime, timedelta
from app.models import ApiKey


def test_old_key_valid_in_grace(db):
    from app.models import Organization, AccountTier, ClientAccount
    org = Organization(name="o", slug="o", quota_usd=100, is_active=True)
    db.add(org); db.commit(); db.refresh(org)
    tier = AccountTier(name="t", rate_limit_per_min=60,
                       cost_per_thousand_input=0.001, cost_per_thousand_output=0.002)
    db.add(tier); db.commit(); db.refresh(tier)
    c = ClientAccount(org_id=org.id, client_identity="k",
                      tier_id=tier.id, credit_balance=10.0, is_active=True)
    db.add(c); db.commit(); db.refresh(c)

    old = ApiKey(client_id=c.id, key_hash="oldhash", key_prefix="oldprefix")
    db.add(old); db.commit()

    now = datetime.utcnow()
    # Revoke but keep grace 1h in the future
    old.revoked_at = now
    old.expires_at = now + timedelta(hours=1)
    db.commit()

    fresh = db.query(ApiKey).filter(ApiKey.key_hash == "oldhash").first()
    assert fresh.revoked_at is not None
    assert fresh.expires_at > now


def test_old_key_invalid_after_grace(db):
    from app.models import ApiKey
    now = datetime.utcnow()
    k = ApiKey(client_id=1, key_hash="x", key_prefix="p",
               revoked_at=now - timedelta(hours=2),
               expires_at=now - timedelta(hours=1))
    db.add(k); db.commit()
    expired = db.query(ApiKey).filter(ApiKey.key_hash == "x").first()
    assert expired.expires_at < now
