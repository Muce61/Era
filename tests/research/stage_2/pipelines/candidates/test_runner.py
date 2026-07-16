from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from era100x.research.stage_2.manifests.models import Stage2ExecutionManifest, canonical_json
from era100x.research.stage_2.pipelines.candidates import runner


def manifest(path: Path) -> Stage2ExecutionManifest:
    item = Stage2ExecutionManifest.seal(
        {
            "schema_name": "stage2-group1-execution",
            "manifest_version": "test",
            "preregistration_manifest_hash": "1" * 64,
            "code_commit": "a" * 40,
            "fixture_logical_hash": "2" * 64,
            "small_sample_validation_hash": "3" * 64,
            "config_hash": "4" * 64,
            "stage1_data_run_id": "stage1",
            "stage1_logical_hashes": {"BTCUSDT": "5" * 64, "ETHUSDT": "6" * 64},
            "full_run_cli": (
                "uv run python scripts/run_stage2_group1_candidates.py "
                "{preflight,run,resume,verify}"
            ),
            "invalidation_conditions": ("test",),
        }
    )
    path.write_text(canonical_json(item.model_dump(mode="python")) + "\n")
    return item


def test_controlled_interruption_resume_publish_and_verify(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path = tmp_path / "execution.json"
    manifest(manifest_path)
    monkeypatch.setattr(runner, "STAGE2_ROOT", tmp_path / "stage2")
    monkeypatch.setattr(runner, "dates", lambda: [date(2020, 1, 1), date(2020, 1, 2)])
    monkeypatch.setenv("ERA_STAGE2_WORKERS", "1")

    def price(**_: object) -> dict[str, list[dict[str, object]]]:
        return {"flow_windows": [], "market_episodes": []}

    def flow(**_: object) -> dict[str, list[dict[str, object]]]:
        return {"flow_features": [], "market_episodes": []}

    monkeypatch.setattr(runner, "build_price_day", price)
    monkeypatch.setattr(runner, "build_flow_day", flow)
    run = runner.CandidateRun.preflight("run-a", manifest_path)
    monkeypatch.setenv("ERA_STAGE2_INTERRUPT_AFTER_PARTITIONS", "1")
    with pytest.raises(InterruptedError, match="controlled"):
        run.execute("BTCUSDT", "V1_PRICE", resume=False)
    monkeypatch.delenv("ERA_STAGE2_INTERRUPT_AFTER_PARTITIONS")
    run.execute("BTCUSDT", "V1_PRICE", resume=True)
    run.execute("BTCUSDT", "V1_FLOW", resume=False)
    run.execute("ETHUSDT", "V1_PRICE", resume=False)
    run.execute("ETHUSDT", "V1_FLOW", resume=False)
    assert run.verify()["entries"]
    with pytest.raises(FileExistsError, match="append-only"):
        runner.CandidateRun.preflight("run-a", manifest_path)


def test_failed_partition_is_not_published(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_path = tmp_path / "execution.json"
    manifest(manifest_path)
    monkeypatch.setattr(runner, "STAGE2_ROOT", tmp_path / "stage2")
    monkeypatch.setattr(runner, "dates", lambda: [date(2020, 1, 1)])
    monkeypatch.setenv("ERA_STAGE2_WORKERS", "1")

    def fail(**_: object) -> dict[str, list[dict[str, object]]]:
        raise RuntimeError("fixture failure")

    monkeypatch.setattr(runner, "build_price_day", fail)
    run = runner.CandidateRun.preflight("run-fail", manifest_path)
    with pytest.raises(RuntimeError, match="fixture failure"):
        run.execute("BTCUSDT", "V1_PRICE", resume=False)
    assert not (run.root / "published" / "data").exists()


def test_catalog_ignores_external_volume_appledouble_sidecars(tmp_path: Path) -> None:
    data = tmp_path / "data" / "dataset" / "date=2020-01-01"
    data.mkdir(parents=True)
    (data / "._part-000.parquet").write_bytes(b"not parquet; macOS metadata only")
    runner.write_partition(data / "part-000.parquet", [{"id": "one"}], "dataset")

    catalog = runner.catalog_tree(tmp_path / "data")

    assert [entry["relative_path"] for entry in catalog["entries"]] == [
        "dataset/date=2020-01-01/part-000.parquet"
    ]
