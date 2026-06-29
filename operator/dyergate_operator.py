"""
DyerGate Kubernetes Operator.

Manages custom resources:
  - DyerGateTenant: an Organization (auto-provisions namespace, quota, secrets)
  - DyerGateClient: a ClientAccount (auto-rotates keys, monitors usage)

Run with:
  kopf run operator/dyergate_operator.py --standalone
"""
import os
import time

import kopf
import kubernetes
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Connect to in-cluster DyerGate DB
DB_URL = os.environ.get("DATABASE_URL", "postgres+psycopg://dyergate:secret@dyergate-db/dyergate")
engine = create_engine(DB_URL)
Session = sessionmaker(bind=engine)

kubernetes.config.load_incluster_config()
v1 = kubernetes.client.CoreV1Api()
custom_api = kubernetes.client.CustomObjectsApi()


@kopf.on.create("dyergate.io", "v1", "dyergatetenants")
def create_tenant(spec, name, namespace, **kwargs):
    """When a DyerGateTenant CR is created, provision an Org in the DyerGate DB."""
    slug = spec.get("slug", name)
    display_name = spec.get("displayName", name)
    quota_usd = spec.get("quotaUsd", 1000.0)
    sso_enabled = spec.get("ssoEnabled", False)

    db = Session()
    try:
        from app.models import Organization
        existing = db.query(Organization).filter(Organization.slug == slug).first()
        if not existing:
            org = Organization(name=display_name, slug=slug, quota_usd=quota_usd, is_active=True)
            db.add(org); db.commit(); db.refresh(org)
            org_id = org.id
        else:
            existing.quota_usd = quota_usd
            existing.is_active = True
            db.commit()
            org_id = existing.id

        # Create namespace for tenant workloads
        try:
            v1.create_namespace(kubernetes.client.V1Namespace(metadata=kubernetes.client.V1ObjectMeta(name=f"tenant-{slug}")))
        except kubernetes.client.exceptions.ApiException as e:
            if e.status != 409:
                raise

        return {"orgId": org_id, "slug": slug, "status": "Provisioned"}
    finally:
        db.close()


@kopf.on.update("dyergate.io", "v1", "dyergatetenants")
def update_tenant(spec, status, **kwargs):
    """Sync quota changes from the CR into the DB."""
    slug = status.get("create_tenant", {}).get("slug")
    if not slug:
        return
    quota_usd = spec.get("quotaUsd", 1000.0)
    db = Session()
    try:
        from app.models import Organization
        org = db.query(Organization).filter(Organization.slug == slug).first()
        if org:
            org.quota_usd = quota_usd
            db.commit()
    finally:
        db.close()


@kopf.on.create("dyergate.io", "v1", "dyergateclients")
def create_client(spec, name, namespace, **kwargs):
    """Provision an API key + secret for a client CR."""
    from app.auth import generate_api_key
    from app.models import ClientAccount, ApiKey, Organization
    tenant_ns = namespace.replace("tenant-", "")
    raw, h, prefix = generate_api_key()

    db = Session()
    try:
        org = db.query(Organization).filter(Organization.slug == tenant_ns).first()
        if not org:
            raise kopf.PermanentError(f"Tenant '{tenant_ns}' not provisioned.")
        # Create a default tier if missing
        from app.models import AccountTier
        tier = db.query(AccountTier).filter(AccountTier.name == "standard").first()
        if not tier:
            tier = AccountTier(name="standard", rate_limit_per_min=60,
                              cost_per_thousand_input=0.002, cost_per_thousand_output=0.003)
            db.add(tier); db.commit(); db.refresh(tier)
        client = ClientAccount(
            org_id=org.id,
            client_identity=spec.get("identity", name),
            tier_id=tier.id, credit_balance=spec.get("creditBalance", 10.0), is_active=True,
        )
        db.add(client); db.commit(); db.refresh(client)
        db.add(ApiKey(client_id=client.id, key_hash=h, key_prefix=prefix))
        db.commit()

        # Store the raw key in a K8s Secret in the tenant's namespace
        secret = kubernetes.client.V1Secret(
            metadata=kubernetes.client.V1ObjectMeta(name=f"dyergate-key-{name}", namespace=namespace),
            string_data={"api-key": raw, "api-key-prefix": prefix,
                         "client-identity": client.client_identity},
            type="Opaque",
        )
        try:
            v1.create_namespaced_secret(namespace, secret)
        except kubernetes.client.exceptions.ApiException as e:
            if e.status == 409:
                v1.replace_namespaced_secret(f"dyergate-key-{name}", namespace, secret)
            else:
                raise
        return {"clientId": client.id, "keyPrefix": prefix, "status": "Provisioned"}
    finally:
        db.close()


@kopf.timer("dyergate.io", "v1", "dyergatetenants", interval=60)
def monitor_tenants(spec, status, **kwargs):
    """Periodically sync tenant usage back to the CR status."""
    slug = status.get("create_tenant", {}).get("slug")
    if not slug:
        return
    db = Session()
    try:
        from app.models import Organization, UsageLedger
        from sqlalchemy import func
        from datetime import datetime, timedelta
        org = db.query(Organization).filter(Organization.slug == slug).first()
        if not org:
            return
        since = datetime.utcnow() - timedelta(hours=1)
        usage = db.query(func.coalesce(func.sum(UsageLedger.total_cost), 0.0)).filter(
            UsageLedger.org_id == org.id, UsageLedger.created_at >= since,
        ).scalar() or 0.0
        return {"lastHourUsageUsd": float(usage), "quotaUsd": org.quota_usd}
    finally:
        db.close()
