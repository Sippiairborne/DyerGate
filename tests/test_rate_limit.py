from app.metering import SlidingWindowLimiter
import pytest


def test_rate_limit_allows_up_to_limit():
    rl = SlidingWindowLimiter(window_seconds=60)
    for _ in range(5):
        rl.check(client_id=1, limit=5)


def test_rate_limit_blocks_over_limit():
    from fastapi import HTTPException
    rl = SlidingWindowLimiter(window_seconds=60)
    for _ in range(3):
        rl.check(client_id=2, limit=3)
    with pytest.raises(HTTPException) as e:
        rl.check(client_id=2, limit=3)
    assert e.value.status_code == 429
