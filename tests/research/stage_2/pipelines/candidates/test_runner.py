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


def test_price_attempts_are_finalized_before_flow_and_resume_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path = tmp_path / "execution.json"
    manifest(manifest_path)
    monkeypatch.setattr(runner, "STAGE2_ROOT", tmp_path / "stage2")
    monkeypatch.setattr(runner, "dates", lambda: [date(2020, 1, 1)])
    monkeypatch.setenv("ERA_STAGE2_WORKERS", "1")

    def price(**kwargs: object) -> dict[str, list[dict[str, object]]]:
        day = kwargs["day"]
        assert day == date(2020, 1, 1)
        start = 1_577_836_800_000_000_000
        canonical_id = "1" * 64
        return {
            "candidate_attempts": [
                {
                    "instrument": "BTCUSDT",
                    "data_run_id": "stage1",
                    "dataset_logical_hash": "5" * 64,
                    "config_hash": "4" * 64,
                    "code_version": "a" * 40,
                    "parameter_set_id": "G1-PRIMARY-V1",
                    "available_at_ts": start + 10,
                    "market_episode_id": "2" * 64,
                    "canonical_candidate_id": canonical_id,
                    "candidate_version_id": canonical_id,
                    "canonical_payload_hash": "3" * 64,
                    "venue": "BINANCE_USDM",
                    "direction": "LONG",
                    "canonical_key_level_id": "4" * 64,
                    "sweep_id": "5" * 64,
                    "reclaim_id": "6" * 64,
                    "hold_id": "7" * 64,
                    "trigger_id": "8" * 64,
                    "flow_feature_set_id": None,
                    "variant": "V1_PRICE",
                    "time_combination_id": "T2",
                    "sweep_start_ns": start,
                    "episode_status": "CANDIDATE",
                    "consumed": False,
                    "consumed_by_intent_id": None,
                    "rearm_eligible_at_ns": None,
                    "event_parameter_set_id": "G1-PRIMARY-V1",
                    "trigger_available_at_ts": start + 10,
                    "window_start_ts": start - 5_000_000_000 + 10,
                    "window_end_ts": start + 10,
                    "source_processing_partition": "2020-01-01",
                    "source_row_ordinal": 0,
                    "source_file_logical_path": (
                        "instrument=BTCUSDT/variant=V1_PRICE/candidate_attempts/"
                        "date=2020-01-01/part-000.parquet"
                    ),
                }
            ]
        }

    monkeypatch.setattr(runner, "build_price_day", price)
    run = runner.CandidateRun.preflight("run-finalize", manifest_path)
    run.execute("BTCUSDT", "V1_PRICE", resume=False)

    episode_path = (
        run.root / "staging/data/instrument=BTCUSDT/variant=V1_PRICE/market_episodes/"
        "date=2020-01-01/part-000.parquet"
    )
    assert episode_path.exists()
    assert runner.pl.read_parquet(episode_path)["canonical_candidate_id"].item() == "1" * 64
    checkpoint = run._checkpoint()
    assert "BTCUSDT:V1_PRICE:FINALIZE" in checkpoint["completed"]
    run.execute("BTCUSDT", "V1_PRICE", resume=True)
    assert run._checkpoint()["completed"].count("BTCUSDT:V1_PRICE:FINALIZE") == 1
