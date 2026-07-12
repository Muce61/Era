import pytest
from era100x.data.reporting.quality import REQUIRED, sample_quality_report


def test_report_is_deterministic_and_not_full_data() -> None:
    values = {k: True for k in reversed(REQUIRED)}
    a = sample_quality_report(values)
    assert a == sample_quality_report(dict(values))
    assert a["full_data_status"] == "NOT_RUN_FULL_DATA"


def test_missing_or_failed_gate_rejects() -> None:
    with pytest.raises(ValueError, match="incomplete"):
        sample_quality_report({})
    values = {k: True for k in REQUIRED}
    values["integrity"] = False
    with pytest.raises(ValueError, match="failed"):
        sample_quality_report(values)
