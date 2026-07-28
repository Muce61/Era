from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]


def test_plan_v18_ui_exposes_evidence_driven_observability() -> None:
    page = (ROOT / "scripts/stage2_progress_ui.html").read_text(encoding="utf-8")
    server = (ROOT / "scripts/run_stage2_progress_server.py").read_text(encoding="utf-8")

    assert 'fetch("/api/v18/status"' in page
    assert "S2P18-T11–T20 Lifecycle Repair Successor" in page
    for marker in (
        "progress_percent",
        "processed_units",
        "total_units",
        "elapsed_seconds",
        "units_per_second",
        "eta_seconds",
        "subphase",
        "heartbeat_at",
        "verify_state",
        "rss_bytes",
    ):
        assert marker in server
    assert 'path == "/api/v18/status"' in server
    assert "formal_run_authorized" in server
