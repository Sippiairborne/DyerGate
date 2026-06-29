import hashlib
import hmac
import json
import logging

import httpx

from app.config import settings
from app.models import Integration

logger = logging.getLogger("dyergate.integrations")


async def _post(url: str, payload: dict, headers: dict = None) -> tuple[bool, int | None, str | None]:
    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            r = await http.post(url, json=payload, headers=headers or {})
            return (200 <= r.status_code < 300), r.status_code, None
    except Exception as e:
        return False, None, str(e)


async def send_pagerduty(Integration_config, event: dict) -> bool:
    cfg = Integration_config.config
    payload = {
        "routing_key": cfg.get("integration_key") or settings.PAGERDUTY_INTEGRATION_KEY,
        "event_action": "trigger",
        "payload": {
            "summary": event.get("title", "DyerGate Alert"),
            "severity": event.get("severity", "warning"),
            "source": event.get("source", "dyergate"),
            "custom_details": event,
        },
    }
    ok, _, err = await _post("https://events.pagerduty.com/v2/enqueue", payload)
    return ok


async def send_opsgenie(Integration_config, event: dict) -> bool:
    cfg = Integration_config.config
    headers = {"Authorization": f"GenieKey {cfg.get('api_key') or settings.OPSGENIE_API_KEY}"}
    payload = {"message": event.get("title", "Alert"), "description": json.dumps(event)}
    ok, _, _ = await _post("https://api.opsgenie.com/v2/alerts", payload, headers)
    return ok


async def send_slack(Integration_config, event: dict) -> bool:
    cfg = Integration_config.config
    url = cfg.get("webhook_url") or settings.SLACK_WEBHOOK_URL
    color = {"critical": "danger", "warning": "warning", "info": "good"}.get(event.get("severity", "info"), "good")
    payload = {
        "channel": cfg.get("channel"),
        "attachments": [{
            "color": color,
            "title": event.get("title", "DyerGate Alert"),
            "text": json.dumps(event, indent=2)[:500],
        }],
    }
    payload = {k: v for k, v in payload.items() if v}
    ok, _, _ = await _post(url, payload)
    return ok


async def send_discord(Integration_config, event: dict) -> bool:
    cfg = Integration_config.config
    url = cfg.get("webhook_url") or settings.DISCORD_WEBHOOK_URL
    color = {"critical": 0xDC2626, "warning": 0xF59E0B, "info": 0x10B981}.get(event.get("severity", "info"), 0x10B981)
    payload = {
        "embeds": [{
            "title": event.get("title", "DyerGate Alert"),
            "description": f"```{json.dumps(event, indent=2)[:1500]}```",
            "color": color,
        }]
    }
    ok, _, _ = await _post(url, payload)
    return ok


async def send_teams(Integration_config, event: dict) -> bool:
    cfg = Integration_config.config
    url = cfg.get("webhook_url") or settings.TEAMS_WEBHOOK_URL
    color = {"critical": "DC2626", "warning": "F59E0B", "info": "10B981"}.get(event.get("severity", "info"), "10B981")
    payload = {
        "@type": "MessageCard",
        "themeColor": color,
        "title": event.get("title", "DyerGate Alert"),
        "text": json.dumps(event, indent=2)[:1000],
    }
    ok, _, _ = await _post(url, payload)
    return ok


HANDLERS = {
    "pagerduty": send_pagerduty,
    "opsgenie": send_opsgenie,
    "slack": send_slack,
    "discord": send_discord,
    "teams": send_teams,
}


async def fire_to_integrations(db, org_id: int, event: dict) -> dict:
    rows = db.query(Integration).filter(
        Integration.org_id == org_id, Integration.is_active == True,
    ).all()
    results = {}
    for r in rows:
        handler = HANDLERS.get(r.kind)
        if handler:
            try:
                results[r.kind] = await handler(r, event)
            except Exception as e:
                results[r.kind] = False
                logger.exception("%s integration failed: %s", r.kind, e)
    return results
