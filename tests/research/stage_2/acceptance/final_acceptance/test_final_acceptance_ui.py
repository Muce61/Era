"""Read-only Plan v1.7 UI contract tests."""

from pathlib import Path


def test_t20_ui_uses_live_v17_projection_and_plan_v13_observability() -> None:
    page = Path("scripts/stage2_progress_ui.html").read_text(encoding="utf-8")
    server = Path("scripts/run_stage2_progress_server.py").read_text(encoding="utf-8")

    assert 'fetch("/api/v17/status"' in page
    assert "S2P17-T20 Final Evidence Acceptance" in page
    assert "hasFinalDecision" in page
    assert ': (plan.status || "CHECKING")' in page
    assert "HASH_CHAIN" in page
    assert "BLIND_EVENT_SELECTION" in page
    assert "EVIDENCE_CARDS" in page
    assert "耗时" in page
    assert "吞吐" in page
    assert "ETA" in page
    assert "5秒自动刷新" in page
    assert "stage2_plan_v17" in server
    assert 'path == "/api/v17/status"' in server


def test_t20_ui_does_not_hardcode_formal_pass() -> None:
    page = Path("scripts/stage2_progress_ui.html").read_text(encoding="utf-8")
    section = page[
        page.index('id="v17FlowTitle"') : page.index("</section>", page.index('id="v17FlowTitle"'))
    ]
    assert ">PASS<" not in section
    assert "STAGE2_NO_GO_CURRENT_EVIDENCE" not in section
