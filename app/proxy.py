# Add at the top of each streaming/blocking/embed function, BEFORE reserve():

from app.quota import enforce_quota

# Example for streaming:
async def run_streaming_chat(upstream_body, client, tier, db, request_id=None):
    provider = get_provider()
    accumulated = []
    upstream_status = {"v": None}
    success = {"v": False}

    input_tokens_est = tokens.count(json.dumps(upstream_body.get("messages", [])))
    cap_out = min(
        upstream_body.get("max_tokens") or settings.MAX_OUTPUT_TOKENS_SAFETY_CAP,
        settings.MAX_OUTPUT_TOKENS_SAFETY_CAP,
    )
    estimated_cost = compute_cost(input_tokens_est, cap_out, tier)

    # NEW: enforce org-level quota
    enforce_quota(db, client.org_id, estimated_cost)

    reserved = reserve(client, estimated_cost)
    db.commit()
    # ... rest unchanged

