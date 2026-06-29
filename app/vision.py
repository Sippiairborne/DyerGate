import base64
import io
import logging
from typing import Optional

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.models import ClientAccount, VisionRequest, ImageGeneration, UsageLedger
from app.metering import tokens, compute_cost, reserve, refund
from app.proxy import run_blocking_chat
from app.upstream import get_provider

logger = logging.getLogger("dyergate.vision")


VISION_PRICING = {
    # USD per image (multimodal input tokens billed separately as chat)
    "gpt-4-vision-preview": 0.01,
    "gpt-4o": 0.005,
    "claude-3-opus": 0.015,
    "claude-3-sonnet": 0.003,
}

IMAGE_GEN_PRICING = {
    "dall-e-3": {"1024x1024": 0.040, "1792x1024": 0.080, "1024x1792": 0.080},
    "dall-e-2": {"1024x1024": 0.020, "512x512": 0.018, "256x256": 0.016},
    "stable-diffusion-3": {"1024x1024": 0.020},
}


async def vision_chat(
    db: Session,
    client: ClientAccount,
    model: str,
    messages: list,
    images: list[dict],  # [{"data":"<base64>","mime":"image/png"}, ...]
    max_tokens: int = 1024,
    request_id: str = None,
) -> dict:
    """Multimodal chat with image inputs."""
    tier = client.tier
    # Convert images to OpenAI vision format
    vision_messages = []
    for m in messages:
        if m["role"] == "user" and images:
            content = [{"type": "text", "text": m["content"]}]
            for img in images:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{img['mime']};base64,{img['data']}"},
                })
            vision_messages.append({"role": m["role"], "content": content})
        else:
            vision_messages.append(m)

    # Cost estimate
    n_images = len(images)
    image_cost = VISION_PRICING.get(model, 0.005) * n_images
    text_tokens = sum(tokens.count(m["content"]) if isinstance(m.get("content"), str) else 0 for m in messages)
    text_cost = compute_cost(text_tokens, 0, tier)
    total_cost = image_cost + text_cost

    if client.credit_balance < total_cost:
        raise HTTPException(status_code=402, detail="Insufficient credit for vision request.")
    reserve(client, total_cost); db.commit()

    body = {"model": model, "messages": vision_messages,
            "max_tokens": max_tokens, "stream": False}

    success = False
    resp = {}
    upstream_status = None
    err = None
    try:
        provider = get_provider()
        async with httpx.AsyncClient(timeout=120.0) as http:
            resp = await provider.chat(body, http)
            upstream_status = 200
            success = True
    except httpx.HTTPStatusError as e:
        upstream_status = e.response.status_code
        err = e.response.text[:300]
    except Exception as e:
        err = str(e)

    actual_cost = total_cost if success else 0.0
    refund(client, total_cost, actual_cost)
    output_text = resp.get("choices", [{}])[0].get("message", {}).get("content", "") if success else ""
    output_tokens = tokens.count(output_text)
    db.add(VisionRequest(
        org_id=client.org_id, client_id=client.id, model=model,
        image_count=n_images, prompt_tokens=text_tokens + n_images * 765,
        completion_tokens=output_tokens, cost=actual_cost, success=success,
        request_id=request_id,
    ))
    db.add(UsageLedger(
        org_id=client.org_id, client_id=client.id, endpoint="/v1/vision/chat",
        model=model, input_tokens=text_tokens + n_images * 765,
        output_tokens=output_tokens, total_cost=actual_cost,
        success=success, upstream_status=upstream_status, request_id=request_id,
    ))
    db.commit()
    if not success:
        raise HTTPException(status_code=502, detail=f"Vision upstream failed: {err}")
    return resp


async def generate_image(
    db: Session,
    client: ClientAccount,
    prompt: str,
    model: str = None,
    size: str = "1024x1024",
    n: int = 1,
    request_id: str = None,
) -> dict:
    model = model or settings.IMAGE_GEN_DEFAULT_MODEL
    if len(prompt) > settings.IMAGE_GEN_MAX_PROMPT_LENGTH:
        raise HTTPException(status_code=400, detail="Prompt too long.")

    pricing = IMAGE_GEN_PRICING.get(model, IMAGE_GEN_PRICING["dall-e-3"])
    unit_cost = pricing.get(size, pricing["1024x1024"])
    total_cost = unit_cost * n
    if client.credit_balance < total_cost:
        raise HTTPException(status_code=402, detail="Insufficient credit for image generation.")
    reserve(client, total_cost); db.commit()

    success = False
    image_urls = []
    err = None
    try:
        provider = get_provider()
        # OpenAI-compat image gen endpoint
        async with httpx.AsyncClient(timeout=180.0) as http:
            url = f"{settings.UPSTREAM_API_URL}/v1/images/generations"
            r = await http.post(url, json={"model": model, "prompt": prompt,
                                          "size": size, "n": n},
                                headers={"Authorization": f"Bearer {settings.UPSTREAM_API_KEY}"}
                                        if settings.UPSTREAM_API_KEY else {})
            if 200 <= r.status_code < 300:
                image_urls = [d["url"] for d in r.json().get("data", []) if "url" in d]
                success = True
            else:
                err = r.text[:300]
    except Exception as e:
        err = str(e)

    actual_cost = total_cost if success else 0.0
    refund(client, total_cost, actual_cost)
    db.add(ImageGeneration(
        org_id=client.org_id, client_id=client.id, model=model,
        prompt=prompt, size=size, n=n, image_urls=image_urls,
        cost=actual_cost, success=success, request_id=request_id,
    ))
    db.commit()
    if not success:
        raise HTTPException(status_code=502, detail=f"Image gen failed: {err}")
    return {"created": True, "data": [{"url": u} for u in image_urls]}
