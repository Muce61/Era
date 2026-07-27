from __future__ import annotations

from pathlib import Path


def test_ui_has_nine_live_t19_modules_and_no_hardcoded_pass() -> None:
    page = (Path(__file__).parents[5] / "scripts" / "stage2_progress_ui.html").read_text(
        encoding="utf-8"
    )
    for phase in (
        "AUDIT",
        "FORMAT_SMOKE",
        "SOURCE_PROJECTION",
        "H2_F1_F10",
        "H3_LIFECYCLE_GATE",
        "PARAMETER_LANDSCAPE",
        "EVIDENCE_CARDS",
        "PUBLISH",
        "VERIFY",
    ):
        assert f'"{phase}"' in page
    assert 'fetch("/api/v16/status"' in page
    assert "evidence.engineering_status" in page
    assert "plan.parameter_landscape_rows" in page
    assert "plan.verify_hash" in page
    assert "plan.run_code_commit" in page
    assert "NO_GO_CURRENT_EVIDENCE</strong>" not in page
