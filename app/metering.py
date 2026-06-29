
import logging
import time
from collections import deque
from threading import Lock
from typing import Dict, Deque

import tiktoken
from fastapi import HTTPException

from app.models import ClientAccount, AccountTier
from app.config import settings

logger = logging.getLogger("dyergate.metering")


class SlidingWindowLimiter:
    """In-memory sliding-window limiter. Single-process only."""
    def __init__(self, window_seconds: int = 60):
        self.window = window_seconds
        self._buckets: Dict[int, Deque[float]] = {}
        self._lock = Lock()

    def check(self, client_id: int, limit: int) -> None:
        now = time.time()
        cutoff = now - self.window
        with self._lock:
            bucket = self._buckets.get(client_id)
            if bucket is None:
                bucket = deque()
                self._buckets[client_id] = bucket
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                raise HTTPException(status_code=429, detail=f"Rate limit exceeded: {limit} req/min.")
            bucket.append(now)

    def cleanup(self) -> int:
        cutoff = time.time() - self.window
        removed = 0
        with self._lock:
            for k in list(self._buckets.keys()):
                bucket = self._buckets[k]
                while bucket and bucket[0] < cutoff:
                    bucket.popleft()
                if not bucket:
                    del self._buckets[k]
                    removed += 1
        return removed


class RedisSlidingWindowLimiter:
    """
    Redis-backed sliding window using sorted sets.
    Accurate across multiple uvicorn workers / pods.
    Key: dyergate:rl:{client_id}
    """
    def __init__(self, redis_url: str, window_seconds: int = 60):
        import redis
        self.r = redis.from_url(redis_url, decode_responses=True)
        self.window = window_seconds

    def check(self, client_id: int, limit: int) -> None:
        now = time.time()
        key = f"dyergate:rl:{client_id}"
        cutoff = now - self.window
        pipe = self.r.pipeline()
        pipe.zremrangebyscore(key, 0, cutoff)
        pipe.zcard(key)
        _, count = pipe.execute()
        if count >= limit:
            raise HTTPException(status_code=429, detail=f"Rate limit exceeded: {limit} req/min.")
        # Add the new timestamp, then expire the key.
        pipe = self.r.pipeline()
        pipe.zadd(key, {f"{now}:{client_id}": now})
        pipe.expire(key, self.window + 5)
        pipe.execute()


class TokenCalculator:
    _instance = None
    def __init__(self):
        self.encoder = tiktoken.get_encoding("cl100k_base")

    @classmethod
    def instance(cls) -> "TokenCalculator":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def count(self, text: str) -> int:
        if not text:
            return 0
        return len(self.encoder.encode(text))


def build_limiter():
    if settings.REDIS_URL:
        logger.info("Using Redis-backed rate limiter: %s", settings.REDIS_URL)
        return RedisSlidingWindowLimiter(settings.REDIS_URL)
    logger.info("Using in-memory rate limiter (single worker only).")
    return SlidingWindowLimiter()


limiter = build_limiter()
tokens = TokenCalculator.instance()


def compute_cost(input_tokens: int, output_tokens: int, tier: AccountTier) -> float:
    base = (
        (input_tokens / 1000.0) * tier.cost_per_thousand_input
        + (output_tokens / 1000.0) * tier.cost_per_thousand_output
    )
    return base * settings.MARGIN_MULTIPLIER


def precheck_balance(client: ClientAccount, approx_cost: float) -> None:
    if client.credit_balance <= 0:
        raise HTTPException(status_code=402, detail="Zero credit balance.")
    if client.credit_balance < approx_cost:
        raise HTTPException(
            status_code=402,
            detail=f"Insufficient credit: balance={client.credit_balance:.4f}, "
                   f"estimated cost≈{approx_cost:.4f}.",
        )


def reserve(client: ClientAccount, amount: float) -> float:
    if amount <= 0:
        return 0.0
    client.credit_balance = max(0.0, client.credit_balance - amount)
    return amount


def refund(client: ClientAccount, reserved: float, actual: float) -> float:
    delta = max(0.0, reserved - actual)
    if delta > 0:
        client.credit_balance += delta
    return reserved - delta
