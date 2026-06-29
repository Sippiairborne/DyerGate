# Add these to the existing admin router:

from app.sso import (
    oidc_authorize_url, oidc_exchange_code, oidc_fetch_userinfo,
    saml_build_auth_request, saml_process_response, provision_or_link_sso_user,
)
from app.models import (
    SsoConfig, SsoUserLink, AgentSkill, AgentInvocation, FeatureFlag,
)
from app.analytics import timeseries, by_model, by_endpoint, top_clients


# ---------- SSO config ----------

@router.post("/sso/{org_id}")
def configure_sso(
    org_id: int,
    method: str,  # "saml" or "oidc"
    issuer: str, sso_url: str,
    certificate: Optional[str] = None,
    client_id: Optional[str] = None, client_secret: Optional[str] = None,
    entity_id: Optional[str] = None,
    default_role: str = "viewer",
    request: Request = None, db: Session = Depends(get_db),
):
    if method not in ("saml", "oidc"):
        raise HTTPException(status_code=400, detail="method must be 'saml' or 'oidc'.")
    existing = db.query(SsoConfig).filter(SsoConfig.org_id == org_id).first()
    if existing:
        existing.method = method
        existing.issuer = issuer
        existing.sso_url = sso_url
        existing.certificate = certificate
        existing.client_id = client_id
        existing.client_secret = client_secret
        existing.entity_id = entity_id
        existing.default_role = default_role
    else:
        existing = SsoConfig(
            org_id=org_id, method=method, issuer=issuer, sso_url=sso_url,
            certificate=certificate, client_id=client_id, client_secret=client_secret,
            entity_id=entity_id, default_role=default_role, is_active=True,
        )
        db.add(existing)
    db.commit()
    record_audit(db, getattr(request.state, "actor", "admin"),
                 "sso.configure", "organization", org_id, {"method": method})
    return {"org_id": org_id, "method": method, "is_active": True}


@router.get("/sso/{org_id}/authorize")
async def sso_authorize(org_id: int, redirect_uri: str, db: Session = Depends(get_db)):
    cfg = db.query(SsoConfig).filter(SsoConfig.org_id == org_id, SsoConfig.is_active == True).first()
    if not cfg:
        raise HTTPException(status_code=404, detail="SSO not configured.")
    state = secrets.token_urlsafe(24)
    if cfg.method == "oidc":
        return {"redirect_url": await oidc_authorize_url(cfg, state, redirect_uri), "state": state}
    return {"redirect_url": await saml_build_auth_request(cfg, state), "state": state}


@router.post("/sso/{org_id}/callback/oidc")
async def sso_oidc_callback(org_id: int, code: str, redirect_uri: str,
                            db: Session = Depends(get_db)):
    cfg = db.query(SsoConfig).filter(SsoConfig.org_id == org_id, SsoConfig.is_active == True).first()
    if not cfg or cfg.method != "oidc":
        raise HTTPException(status_code=404, detail="OIDC not configured.")
    tokens = await oidc_exchange_code(cfg, code, redirect_uri)
    info = await oidc_fetch_userinfo(cfg, tokens["access_token"])
    user = provision_or_link_sso_user(db, cfg, info["sub"], info.get("email"))
    return {"user_id": user.id, "email": user.email}


@router.post("/sso/{org_id}/callback/saml")
async def sso_saml_callback(org_id: int, SAMLResponse: str, db: Session = Depends(get_db)):
    cfg = db.query(SsoConfig).filter(SsoConfig.org_id == org_id, SsoConfig.is_active == True).first()
    if not cfg or cfg.method != "saml":
        raise HTTPException(status_code=404, detail="SAML not configured.")
    parsed = saml_process_response(cfg, SAMLResponse)
    user = provision_or_link_sso_user(db, cfg, parsed["subject"], parsed.get("email"))
    return {"user_id": user.id, "email": user.email}


# ---------- Agent Marketplace (admin: approval + registration) ----------

@router.post("/marketplace/skills")
def register_skill(
    slug: str, name: str, endpoint_url: str, parameters_schema: str,
    cost_per_invocation: float = 0.001, category: Optional[str] = None,
    description: Optional[str] = None, auth_header: Optional[str] = None,
    request: Request = None, db: Session = Depends(get_db),
):
    import json as _json
    try:
        schema = _json.loads(parameters_schema) if isinstance(parameters_schema, str) else parameters_schema
    except Exception:
        raise HTTPException(status_code=400, detail="parameters_schema must be valid JSON.")
    if db.query(AgentSkill).filter(AgentSkill.slug == slug).first():
        raise HTTPException(status_code=409, detail="Slug already exists.")
    skill = AgentSkill(
        slug=slug, name=name, description=description, category=category,
        provider_org_id=1,  # platform org; override for marketplace users
        endpoint_url=endpoint_url, auth_header=auth_header,
        parameters_schema=schema, cost_per_invocation=cost_per_invocation,
        is_approved=False, is_active=True,
    )
    db.add(skill); db.commit(); db.refresh(skill)
    record_audit(db, getattr(request.state, "actor", "admin"),
                 "skill.register", "agent_skill", skill.id, {"slug": slug})
    return {"id": skill.id, "slug": skill.slug, "is_approved": False}


@router.post("/marketplace/skills/{skill_id}/approve")
def approve_skill(skill_id: int, request: Request = None, db: Session = Depends(get_db)):
    s = db.query(AgentSkill).filter(AgentSkill.id == skill_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Skill not found.")
    s.is_approved = True
    db.commit()
    record_audit(db, getattr(request.state, "actor", "admin"),
                 "skill.approve", "agent_skill", skill_id)
    return {"id": skill_id, "is_approved": True}


@router.get("/marketplace/skills")
def list_skills(approved_only: bool = True, db: Session = Depends(get_db)):
    q = db.query(AgentSkill).filter(AgentSkill.is_active == True)
    if approved_only:
        q = q.filter(AgentSkill.is_approved == True)
    return [{
        "id": s.id, "slug": s.slug, "name": s.name, "description": s.description,
        "category": s.category, "icon_url": s.icon_url,
        "parameters_schema": s.parameters_schema, "cost_per_invocation": s.cost_per_invocation,
    } for s in q.all()]


@router.post("/marketplace/skills/{skill_slug}/invoke")
async def invoke_skill_route(
    skill_slug: str, payload: dict,
    request: Request = None,
    client: ClientAccount = Depends(verify_client),
    db: Session = Depends(get_db),
):
    from app.marketplace import invoke_skill
    rid = getattr(request.state, "request_id", None) if request else None
    return await invoke_skill(db, client, skill_slug, payload, rid)


# ---------- Analytics (admin: org-scoped) ----------

@router.get("/analytics/timeseries")
def analytics_timeseries(org_id: int, days: int = 30, granularity: str = "day",
                         db: Session = Depends(get_db)):
    return timeseries(db, org_id, days, granularity)


@router.get("/analytics/by_model")
def analytics_by_model(org_id: int, days: int = 30, db: Session = Depends(get_db)):
    return by_model(db, org_id, days)


@router.get("/analytics/by_endpoint")
def analytics_by_endpoint(org_id: int, days: int = 30, db: Session = Depends(get_db)):
    return by_endpoint(db, org_id, days)


@router.get("/analytics/top_clients")
def analytics_top_clients(org_id: int, days: int = 30, limit: int = 10,
                          db: Session = Depends(get_db)):
    return top_clients(db, org_id, days, limit)


# ---------- Feature flags ----------

@router.post("/features/{key}")
def set_feature_flag(
    key: str, enabled: bool, org_id: Optional[int] = None, rollout_pct: int = 100,
    request: Request = None, db: Session = Depends(get_db),
):
    flag = db.query(FeatureFlag).filter(
        FeatureFlag.key == key, FeatureFlag.org_id == org_id
    ).first()
    if flag:
        flag.enabled = enabled
        flag.rollout_pct = max(0, min(100, rollout_pct))
    else:
        flag = FeatureFlag(key=key, enabled=enabled, org_id=org_id,
                          rollout_pct=max(0, min(100, rollout_pct)))
        db.add(flag)
    db.commit()
    record_audit(db, getattr(request.state, "actor", "admin"),
                 "feature.flag_set", "feature_flag", key,
                 {"enabled": enabled, "org_id": org_id, "rollout_pct": rollout_pct})
    return {"key": key, "enabled": enabled, "org_id": org_id, "rollout_pct": rollout_pct}


@router.get("/features")
def list_features(org_id: Optional[int] = None, db: Session = Depends(get_db)):
    flags = db.query(FeatureFlag).filter(
        (FeatureFlag.org_id == org_id) | (FeatureFlag.org_id.is_(None))
    ).all()
    return [{"key": f.key, "enabled": f.enabled, "rollout_pct": f.rollout_pct,
             "org_id": f.org_id} for f in flags]


def is_feature_enabled(db: Session, key: str, org_id: Optional[int] = None) -> bool:
    flag = db.query(FeatureFlag).filter(
        FeatureFlag.key == key, FeatureFlag.org_id == org_id
    ).first()
    if flag:
        return flag.enabled
    flag = db.query(FeatureFlag).filter(
        FeatureFlag.key == key, FeatureFlag.org_id.is_(None)
    ).first()
    return bool(flag and flag.enabled)



from app.forecast import forecast
from app.integrations import fire_to_integrations
from app.models import Integration, ForecastRun

@router.post("/forecast")
def run_forecast(org_id: int, horizon_days: int = 30,
                db: Session = Depends(get_db)):
    run = forecast(db, org_id, horizon_days)
    return {
        "id": run.id,
        "horizon_days": run.horizon_days,
        "predicted_total_cost": run.predicted_total_cost,
        "predicted_input_tokens": run.predicted_input_tokens,
        "predicted_output_tokens": run.predicted_output_tokens,
        "predicted_requests": run.predicted_requests,
        "daily_forecast": run.daily_forecast,
        "confidence_low": run.confidence_low,
        "confidence_high": run.confidence_high,
        "model_used": run.model_used,
        "created_at": run.created_at.isoformat(),
    }


@router.get("/forecast/{org_id}")
def latest_forecast(org_id: int, db: Session = Depends(get_db)):
    run = db.query(ForecastRun).filter(
        ForecastRun.org_id == org_id,
    ).order_by(ForecastRun.created_at.desc()).first()
    if not run:
        return None
    return {
        "predicted_total_cost": run.predicted_total_cost,
        "horizon_days": run.horizon_days,
        "daily_forecast": run.daily_forecast,
    }


@router.post("/integrations")
def add_integration(
    org_id: int, kind: str, config: str,
    request: Request = None, db: Session = Depends(get_db),
):
    import json as _json
    if kind not in ("pagerduty", "opsgenie", "slack", "discord", "teams"):
        raise HTTPException(status_code=400, detail=f"Unknown integration: {kind}")
    cfg = _json.loads(config) if isinstance(config, str) else config
    integ = Integration(org_id=org_id, kind=kind, config=cfg, is_active=True)
    db.add(integ); db.commit(); db.refresh(integ)
    record_audit(db, getattr(request.state, "actor", "admin"),
                 "integration.add", "integration", integ.id, {"kind": kind})
    return {"id": integ.id, "kind": kind}


@router.post("/integrations/{integration_id}/test")
async def test_integration(integration_id: int, db: Session = Depends(get_db)):
    integ = db.query(Integration).filter(Integration.id == integration_id).first()
    if not integ:
        raise HTTPException(status_code=404, detail="Integration not found.")
    results = await fire_to_integrations(db, integ.org_id, {
        "title": "DyerGate test alert",
        "severity": "info",
        "source": "dyergate_admin",
    })
    return results
