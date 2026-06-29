import pytest
from app.metering import compute_cost, reserve, refund
from app.models import AccountTier


def make_tier():
    return AccountTier(name="t", rate_limit_per_min=10,
                       cost_per_thousand_input=1.0, cost_per_thousand_output=2.0)


def test_compute_cost_basic():
    t = make_tier()
    # 1000 input tokens @ $1/1k + 500 output tokens @ $2/1k = $1 + $1 = $2
    assert compute_cost(1000, 500, t) == pytest.approx(2.0)


def test_compute_cost_zero():
    assert compute_cost(0, 0, make_tier()) == 0


def test_reserve_refund_no_negative():
    t = make_tier()
    class FakeClient:
        credit_balance = 10.0
    c = FakeClient()
    reserved = reserve(c, 5.0)
    assert c.credit_balance == 5.0
    assert reserved == 5.0
    actual = refund(c, reserved, 2.0)
    assert actual == 2.0
    assert c.credit_balance == 8.0


def test_reserve_clamps_to_zero():
    class C:
        credit_balance = 1.0
    reserve(C, 5.0)
    assert C.credit_balance == 0.0
