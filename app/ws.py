import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Dict, Set

from fastapi import WebSocket, WebSocketDisconnect, Query
from sqlalchemy.orm import Session

from app.auth import hash_key
from app.database import SessionLocal
from app.models import ClientAccount, ApiKey, WsConnection, WsRoom, UsageLedger
from app.metering import tokens, compute_cost, reserve, refund
from app.proxy import _format_openai_chunk
from app.upstream import get_provider, StreamChunk
from app.config import settings

logger = logging.getLogger("dyergate.ws")


class RoomManager:
    """Tracks active rooms and subscribers."""

    def __init__(self):
        self._rooms: Dict[str, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def join(self, room: str, ws: WebSocket) -> None:
        async with self._lock:
            self._rooms.setdefault(room, set()).add(ws)

    async def leave(self, room: str, ws: WebSocket) -> None:
        async with self._lock:
            if room in self._rooms:
                self._rooms[room].discard(ws)
                if not self._rooms[room]:
                    del self._rooms[room]

    async def broadcast(self, room: str, message: dict) -> int:
        async with self._lock:
            subscribers = list(self._rooms.get(room, set()))
        sent = 0
        for ws in subscribers:
            try:
                await ws.send_json(message)
                sent += 1
            except Exception:
                pass
        return sent


rooms = RoomManager()


async def authenticate_ws(api_key: str, db: Session) -> ClientAccount:
    if not api_key or not api_key.startswith("dg_"):
        return None
    key_hash = hash_key(api_key)
    key_row = db.query(ApiKey).filter(ApiKey.key_hash == key_hash).first()
    if not key_row or (key_row.revoked_at and (not key_row.expires_at or key_row.expires_at < datetime.utcnow())):
        return None
    client = db.query(ClientAccount).filter(ClientAccount.id == key_row.client_id).first()
    if not client or not client.is_active or client.credit_balance <= 0:
        return None
    return client


async def chat_websocket(websocket: WebSocket):
    """Main WebSocket endpoint: bidirectional chat streaming + room events."""
    await websocket.accept()
    api_key = websocket.query_params.get("api_key") or websocket.headers.get("authorization", "").replace("Bearer ", "")
    db = SessionLocal()
    client = await authenticate_ws(api_key, db)
    if not client:
        await websocket.send_json({"error": "invalid_api_key"})
        await websocket.close(code=1008)
        db.close()
        return

    conn = WsConnection(client_id=client.id, org_id=client.org_id,
                       session_id=id(websocket).__str__(), ip_address=websocket.client.host if websocket.client else None)
    db.add(conn); db.commit()
    conn_id = conn.id
    db.close()

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                await websocket.send_json({"error": "invalid_json"})
                continue

            action = msg.get("action")
            if action == "chat":
                await _handle_chat(websocket, client, msg)
            elif action == "join_room":
                await rooms.join(msg["room"], websocket)
                await websocket.send_json({"action": "joined", "room": msg["room"]})
            elif action == "leave_room":
                await rooms.leave(msg["room"], websocket)
                await websocket.send_json({"action": "left", "room": msg["room"]})
            elif action == "publish":
                sent = await rooms.broadcast(msg["room"], {
                    "action": "event", "room": msg["room"],
                    "from": client.client_identity, "data": msg.get("data"),
                    "ts": datetime.utcnow().isoformat(),
                })
                await websocket.send_json({"action": "published", "recipients": sent})
            elif action == "ping":
                await websocket.send_json({"action": "pong", "ts": time.time()})
            else:
                await websocket.send_json({"error": f"unknown_action:{action}"})
    except WebSocketDisconnect:
        pass
    finally:
        db = SessionLocal()
        db.query(WsConnection).filter(WsConnection.id == conn_id).delete()
        db.commit()
        db.close()


async def _handle_chat(websocket: WebSocket, client: ClientAccount, msg: dict):
    """Stream a chat completion over the WebSocket, chunk by chunk."""
    messages = msg.get("messages", [])
    model = msg.get("model", "llama3")
    if not messages:
        await websocket.send_json({"error": "messages_required"})
        return

    tier = client.tier
    input_text = json.dumps(messages)
    input_tokens = tokens.count(input_text)
    estimated = compute_cost(input_tokens, 0, tier)
    if client.credit_balance < estimated:
        await websocket.send_json({"error": "insufficient_credit", "balance": client.credit_balance})
        return

    db = SessionLocal()
    try:
        reserve(client, estimated); db.commit()
        provider = get_provider()
        accumulated = []
        try:
            async with __import__("httpx").AsyncClient(timeout=settings.REQUEST_TIMEOUT_SECONDS) as http:
                async for sc in provider.stream_chat({"model": model, "messages": messages, "stream": True}, http):
                    if sc.text:
                        accumulated.append(sc.text)
                    await websocket.send_json({
                        "action": "chunk", "delta": sc.text,
                        "done": sc.done, "model": model,
                    })
                    if sc.done:
                        break
            # Bill actual
            output_tokens = tokens.count("".join(accumulated))
            actual = compute_cost(input_tokens, output_tokens, tier)
            refund(client, estimated, actual)
            db.add(UsageLedger(org_id=client.org_id, client_id=client.id,
                              endpoint="/ws/chat", model=model,
                              input_tokens=input_tokens, output_tokens=output_tokens,
                              total_cost=actual, success=True))
            db.commit()
            await websocket.send_json({"action": "complete", "cost": actual,
                                       "input_tokens": input_tokens,
                                       "output_tokens": output_tokens})
        except Exception as e:
            refund(client, estimated, 0)
            await websocket.send_json({"error": "upstream_error", "detail": str(e)})
    finally:
        db.close()
