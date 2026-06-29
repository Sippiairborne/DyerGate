
import logging
from dataclasses import dataclass
from typing import AsyncIterator, Protocol

import httpx

from app.config import settings

logger = logging.getLogger("dyergate.upstream")


@dataclass
class StreamChunk:
    text: str
    done: bool = False
    raw: dict | None = None


class UpstreamProvider(Protocol):
    name: str

    async def stream_chat(
        self, body: dict, client_factory: httpx.AsyncClient
    ) -> AsyncIterator[StreamChunk]: ...

    async def chat(self, body: dict, client_factory: httpx.AsyncClient) -> dict: ...

    async def list_models(self, client_factory: httpx.AsyncClient) -> list[dict]: ...

    async def embed(self, body: dict, client_factory: httpx.AsyncClient) -> dict: ...


class OllamaProvider:
    name = "ollama"

    def __init__(self, base_url: str, path: str):
        self.base_url = base_url.rstrip("/")
        self.path = path

    async def stream_chat(self, body, http):
        url = f"{self.base_url}{self.path}"
        async with http.stream("POST", url, json={**body, "stream": True}) as r:
            r.raise_for_status()
            buf = b""
            async for chunk in r.aiter_bytes():
                if not chunk:
                    continue
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        import json
                        obj = json.loads(line)
                    except Exception:
                        continue
                    msg = obj.get("message") or {}
                    yield StreamChunk(text=msg.get("content", ""), done=bool(obj.get("done")), raw=obj)
            # Flush trailing
            if buf.strip():
                try:
                    import json
                    obj = json.loads(buf.strip())
                    msg = obj.get("message") or {}
                    yield StreamChunk(text=msg.get("content", ""), done=True, raw=obj)
                except Exception:
                    pass

    async def chat(self, body, http):
        url = f"{self.base_url}{self.path}"
        r = await http.post(url, json={**body, "stream": False})
        r.raise_for_status()
        return r.json()

    async def list_models(self, http):
        r = await http.get(f"{self.base_url}/api/tags")
        r.raise_for_status()
        data = r.json()
        return [
            {
                "id": m.get("name"),
                "object": "model",
                "owned_by": "local",
                "created": 0,
            }
            for m in data.get("models", [])
        ]

    async def embed(self, body, http):
        # Ollama /api/embeddings
        url = f"{self.base_url}/api/embeddings"
        model = body.get("model", "nomic-embed-text")
        inp = body.get("input")
        if isinstance(inp, list):
            # Return an OpenAI-shaped multi-embedding response by aggregating.
            embeddings = []
            total_tokens = 0
            for prompt in inp:
                r = await http.post(url, json={"model": model, "prompt": prompt})
                r.raise_for_status()
                d = r.json()
                embeddings.append(d.get("embedding", []))
            return {
                "object": "list",
                "data": [
                    {"object": "embedding", "embedding": e, "index": i}
                    for i, e in enumerate(embeddings)
                ],
                "model": model,
                "usage": {"prompt_tokens": 0, "total_tokens": 0},
            }
        r = await http.post(url, json={"model": model, "prompt": inp})
        r.raise_for_status()
        d = r.json()
        return {
            "object": "list",
            "data": [{"object": "embedding", "embedding": d.get("embedding", []), "index": 0}],
            "model": model,
            "usage": {"prompt_tokens": 0, "total_tokens": 0},
        }


class OpenAICompatProvider:
    """For OpenAI, Together, Groq, vLLM OpenAI-server, LM Studio, etc."""

    def __init__(self, base_url: str, api_key: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    async def stream_chat(self, body, http):
        url = f"{self.base_url}/v1/chat/completions"
        headers = self._headers()
        async with http.stream(
            "POST", url, json={**body, "stream": True}, headers=headers
        ) as r:
            r.raise_for_status()
            buf = b""
            async for chunk in r.aiter_bytes():
                if not chunk:
                    continue
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    line = line.decode("utf-8", errors="ignore").strip()
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        yield StreamChunk(text="", done=True)
                        return
                    try:
                        import json
                        obj = json.loads(payload)
                    except Exception:
                        continue
                    choices = obj.get("choices") or []
                    if choices:
                        delta = choices[0].get("delta") or {}
                        yield StreamChunk(text=delta.get("content", "") or "", done=False, raw=obj)
            yield StreamChunk(text="", done=True)

    async def chat(self, body, http):
        url = f"{self.base_url}/v1/chat/completions"
        r = await http.post(url, json={**body, "stream": False}, headers=self._headers())
        r.raise_for_status()
        return r.json()

    async def list_models(self, http):
        r = await http.get(f"{self.base_url}/v1/models", headers=self._headers())
        r.raise_for_status()
        return r.json().get("data", [])

    async def embed(self, body, http):
        url = f"{self.base_url}/v1/embeddings"
        r = await http.post(url, json=body, headers=self._headers())
        r.raise_for_status()
        return r.json()


# Registry — selected via env
def get_provider() -> UpstreamProvider:
    kind = settings.UPSTREAM_PROVIDER.lower()
    if kind == "ollama":
        return OllamaProvider(settings.UPSTREAM_API_URL, settings.UPSTREAM_API_PATH)
    if kind in ("openai", "openai_compat", "vllm", "openai-compatible"):
        return OpenAICompatProvider(
            settings.UPSTREAM_API_URL,
            settings.UPSTREAM_API_KEY or None,
        )
    raise RuntimeError(f"Unknown UPSTREAM_PROVIDER: {kind}")
