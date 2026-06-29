import io
import logging
import time

import httpx
from fastapi import HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from app.config import settings
from app.models import ClientAccount, VoiceTranscription, VoiceSynthesis, UsageLedger
from app.metering import reserve, refund
from app.upstream import get_provider

logger = logging.getLogger("dyergate.voice")


VOICE_PRICING = {
    # USD per second (input audio or output speech)
    "whisper-1": 0.0001,
    "tts-1": 0.000015,
    "tts-1-hd": 0.000030,
    "eleven_monolingual_v1": 0.0001,
}


async def transcribe(
    db: Session,
    client: ClientAccount,
    file: UploadFile,
    model: str = None,
    language: str = None,
    request_id: str = None,
) -> dict:
    model = model or settings.VOICE_DEFAULT_MODEL
    content = await file.read()
    size_mb = len(content) / (1024 * 1024)
    if size_mb > settings.VOICE_MAX_FILE_SIZE_MB:
        raise HTTPException(status_code=413, detail=f"File too large ({size_mb:.1f}MB).")

    rate = VOICE_PRICING.get(model, 0.0001)
    estimated_cost = size_mb * 12 * rate  # rough estimate: ~12s audio per MB
    if client.credit_balance < estimated_cost:
        raise HTTPException(status_code=402, detail="Insufficient credit for transcription.")
    reserve(client, estimated_cost); db.commit()

    provider = get_provider()
    # Forward to upstream (OpenAI-compat Whisper endpoint)
    files = {"file": (file.filename or "audio.mp3", io.BytesIO(content), file.content_type or "audio/mpeg")}
    data = {"model": model}
    if language:
        data["language"] = language

    success = False
    text = ""
    upstream_status = None
    err = None
    try:
        async with httpx.AsyncClient(timeout=120.0) as http:
            url = f"{settings.UPSTREAM_API_URL}/v1/audio/transcriptions"
            r = await http.post(url, files=files, data=data,
                                headers={"Authorization": f"Bearer {settings.UPSTREAM_API_KEY}"}
                                if settings.UPSTREAM_API_KEY else {})
            upstream_status = r.status_code
            if 200 <= r.status_code < 300:
                text = r.json().get("text", "")
                success = True
            else:
                err = r.text[:300]
    except Exception as e:
        err = str(e)

    actual_cost = estimated_cost if success else 0.0
    refund(client, estimated_cost, actual_cost)
    db.add(VoiceTranscription(
        org_id=client.org_id, client_id=client.id, model=model,
        duration_seconds=size_mb * 12, file_size_bytes=len(content),
        language=language, text=text, cost=actual_cost, success=success,
        request_id=request_id,
    ))
    db.add(UsageLedger(
        org_id=client.org_id, client_id=client.id, endpoint="/v1/audio/transcriptions",
        model=model, input_tokens=0, output_tokens=int(len(text) / 4),
        total_cost=actual_cost, success=success, upstream_status=upstream_status,
        request_id=request_id,
    ))
    db.commit()
    if not success:
        raise HTTPException(status_code=502, detail=f"Transcription failed: {err}")
    return {"text": text}


async def synthesize(
    db: Session,
    client: ClientAccount,
    text: str,
    model: str = None,
    voice: str = "alloy",
    response_format: str = "mp3",
    request_id: str = None,
) -> bytes:
    from fastapi.responses import Response
    model = model or settings.TTS_DEFAULT_MODEL
    if not text or len(text) > 4096:
        raise HTTPException(status_code=400, detail="Text must be 1-4096 characters.")

    rate = VOICE_PRICING.get(model, 0.000015)
    estimated_cost = len(text) * rate
    if client.credit_balance < estimated_cost:
        raise HTTPException(status_code=402, detail="Insufficient credit for synthesis.")
    reserve(client, estimated_cost); db.commit()

    success = False
    audio_bytes = b""
    err = None
    try:
        async with httpx.AsyncClient(timeout=120.0) as http:
            url = f"{settings.UPSTREAM_API_URL}/v1/audio/speech"
            r = await http.post(
                url,
                json={"model": model, "input": text, "voice": voice,
                      "response_format": response_format},
                headers={"Authorization": f"Bearer {settings.UPSTREAM_API_KEY}"}
                        if settings.UPSTREAM_API_KEY else {},
            )
            if 200 <= r.status_code < 300:
                audio_bytes = r.content
                success = True
            else:
                err = r.text[:300]
    except Exception as e:
        err = str(e)

    actual_cost = estimated_cost if success else 0.0
    refund(client, estimated_cost, actual_cost)
    db.add(VoiceSynthesis(
        org_id=client.org_id, client_id=client.id, model=model, voice=voice,
        input_text_length=len(text),
        output_audio_seconds=len(audio_bytes) / 16000 if audio_bytes else 0,
        cost=actual_cost, success=success, request_id=request_id,
    ))
    db.add(UsageLedger(
        org_id=client.org_id, client_id=client.id, endpoint="/v1/audio/speech",
        model=model, input_tokens=int(len(text) / 4), output_tokens=0,
        total_cost=actual_cost, success=success, request_id=request_id,
    ))
    db.commit()
    if not success:
        raise HTTPException(status_code=502, detail=f"Synthesis failed: {err}")
    return audio_bytes
