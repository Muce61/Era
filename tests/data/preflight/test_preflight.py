from scripts.preflight_stage1_full_data import estimate, periods


def test_period_plan_and_space_gate() -> None:
    assert len(periods()) == 162
    failed = estimate(100, 10, 50, 100)
    assert failed["passes_space_gate"] is False
    passed = estimate(100, 10, 50, 10**12)
    assert passed["passes_space_gate"] is True
