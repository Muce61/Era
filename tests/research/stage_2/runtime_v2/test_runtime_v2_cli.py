from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import freeze_stage2_v2_authorities as authority_cli
from scripts.freeze_stage2_v2_authorities import parser as authority_parser
from scripts.record_stage2_v2_quality_evidence import parser as quality_parser
from scripts.run_stage2_research import COMMANDS, parser


def _authority_args() -> list[str]:
    return [
        "--run-id",
        "stage2-g1-v2-b-test",
        "--manifest",
        "/Volumes/FuckingLife/era100x_stage2/manifests/runtime.json",
        "--snapshot-id",
        "a" * 64,
        "--run-a-protection",
        "/Volumes/FuckingLife/era100x_stage2/manifests/protection.json",
        "--migration-manifest",
        "/Volumes/FuckingLife/era100x_stage2/manifests/migration.json",
    ]


@pytest.mark.parametrize("command", COMMANDS)
def test_every_command_requires_explicit_locked_authorities(command: str) -> None:
    args = parser().parse_args([command, *_authority_args()])
    assert args.command == command
    assert args.snapshot_id == "a" * 64


@pytest.mark.parametrize("flag", ("--root", "--instrument", "--variant", "--workers"))
def test_cli_rejects_runtime_overrides(flag: str) -> None:
    with pytest.raises(SystemExit):
        parser().parse_args(["build-foundation", *_authority_args(), flag, "BTCUSDT"])


def test_cli_exposes_only_the_frozen_command_surface() -> None:
    assert COMMANDS == (
        "preflight",
        "build-foundation",
        "run-group1",
        "resume",
        "release",
        "verify",
        "compare",
    )


def test_operator_preparation_commands_have_no_root_or_semantic_overrides() -> None:
    quality = quality_parser().parse_args(["--transition-run-id", "stage2-g1-v2-authority-test"])
    assert quality.transition_run_id == "stage2-g1-v2-authority-test"
    authorities = authority_parser().parse_args(
        [
            "--transition-run-id",
            "stage2-g1-v2-authority-test",
            "--destination-run-id",
            "stage2-g1-v2-b-test",
            "--quality-evidence",
            "/Volumes/FuckingLife/era100x_stage2/runs/evidence.json",
            "--memory-evidence",
            "/Volumes/FuckingLife/era100x_stage2/runs/memory.json",
            "--finalization-memory-evidence",
            "/Volumes/FuckingLife/era100x_stage2/runs/finalization-memory.json",
        ]
    )
    assert authorities.destination_run_id == "stage2-g1-v2-b-test"
    assert authorities.action == "freeze"
    with pytest.raises(SystemExit):
        authority_parser().parse_args(
            [
                "--transition-run-id",
                "stage2-g1-v2-authority-test",
                "--destination-run-id",
                "stage2-g1-v2-b-test",
                "--quality-evidence",
                "/Volumes/FuckingLife/era100x_stage2/runs/evidence.json",
                "--memory-evidence",
                "/Volumes/FuckingLife/era100x_stage2/runs/memory.json",
                "--finalization-memory-evidence",
                "/Volumes/FuckingLife/era100x_stage2/runs/finalization-memory.json",
                "--instrument",
                "BTCUSDT",
            ]
        )


def test_authority_cli_exposes_explicit_record_failure_action() -> None:
    args = authority_parser().parse_args(
        [
            "record-failure",
            "--transition-run-id",
            "stage2-g1-v2-authority-failed",
            "--failure-log",
            "/Volumes/FuckingLife/era100x_stage2/runs/failed/logs/traceback.log",
            "--failed-code-commit",
            "18d6660bd75a0ba6750d55c29ba45df0cfa1de51",
        ]
    )

    assert args.action == "record-failure"
    assert args.error_type == "ValidationError"
    assert args.failure_field == "archive_partition"
    assert args.destination_run_id is None
    assert args.quality_evidence is None
    assert args.memory_evidence is None
    assert args.finalization_memory_evidence is None


def test_record_failure_receipt_is_write_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runs_root = tmp_path / "runs"
    transition_id = "stage2-g1-v2-authority-failed"
    transition_root = runs_root / transition_id
    failure_log = transition_root / "logs" / "traceback.log"
    failure_log.parent.mkdir(parents=True)
    failure_log.write_text("archive_partition rejected 2026-07-01\n", encoding="utf-8")
    partial = transition_root / "manifests" / "contract-price-inventory-v2.json"
    partial.parent.mkdir(parents=True)
    partial.write_text('{"status":"PARTIAL"}\n', encoding="utf-8")
    monkeypatch.setattr(authority_cli, "RUNS_ROOT", runs_root)
    monkeypatch.setattr(Path, "is_mount", lambda _path: True)
    argv = [
        "record-failure",
        "--transition-run-id",
        transition_id,
        "--failure-log",
        str(failure_log),
        "--failed-code-commit",
        "18d6660bd75a0ba6750d55c29ba45df0cfa1de51",
    ]

    assert authority_cli.main(argv) == 0
    receipt_path = transition_root / "reports" / "authority-freeze-failure.json"
    original = receipt_path.read_bytes()
    assert authority_cli.main(argv) == 0
    receipt = json.loads(receipt_path.read_bytes())

    assert receipt_path.read_bytes() == original
    assert receipt["status"] == "FAILED_AUTHORITY_FREEZE"
    assert receipt["change_request"] == "CR-2026-009"
    assert receipt["failure_field"] == "archive_partition"
    assert receipt["failed_code_commit"] == "18d6660bd75a0ba6750d55c29ba45df0cfa1de51"
    assert receipt["existing_manifest_physical_sha256s"] == {
        "manifests/contract-price-inventory-v2.json": authority_cli.sha256_file(partial)
    }
    with pytest.raises(SystemExit):
        authority_parser().parse_args([*argv, "--error-type", "DifferentError"])
    failure_log.write_text("different immutable failure evidence\n", encoding="utf-8")
    with pytest.raises(FileExistsError, match="append-only authority differs"):
        authority_cli.main(argv)


def test_freeze_writes_deterministic_authority_bundle_receipt_without_creating_run_b(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runs_root = tmp_path / "runs"
    transition_id = "stage2-g1-v2-authority-success"
    destination_id = "stage2-g1-v2-b-reserved"
    transition_root = runs_root / transition_id
    quality_path = transition_root / "reports" / "quality.json"
    memory_path = (
        runs_root / "stage2-g1-v2-memory-diagnostic-cr-2026-011-test" / "reports" / "memory.json"
    )
    finalization_memory_path = (
        runs_root
        / "stage2-g1-v2-finalization-diagnostic-cr-2026-012-test"
        / "reports"
        / "finalization-memory.json"
    )
    quality_path.parent.mkdir(parents=True)
    commit = "1" * 40
    tree_sha256 = "2" * 64
    quality_path.write_text(
        json.dumps(
            {
                "status": "PASS",
                "code_commit": commit,
                "runtime_v2_code_tree_sha256": tree_sha256,
                "created_at": "2026-07-18T00:00:00Z",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    memory_path.parent.mkdir(parents=True)
    memory_path.write_text(
        json.dumps(
            {
                "status": "PASS",
                "change_request": "CR-2026-011",
                "diagnostic_run_id": "stage2-g1-v2-memory-diagnostic-cr-2026-011-test",
                "deterministic_replay": "PASS",
                "semantic_regression": "PASS",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    finalization_memory_path.parent.mkdir(parents=True)
    finalization_memory_path.write_text(
        json.dumps(
            {
                "result": "PASS",
                "change_request": "CR-2026-012",
                "read_only_source": True,
                "packed_row_group_count": 9504,
                "receipt_count": 9504,
                "max_arrow_bytes": 15_120_000,
                "max_current_rss_bytes": 544_030_720,
                "max_phase_current_rss_delta_bytes": 384_630_784,
                "limits": {
                    "arrow_inflight_bytes": 1_073_741_824,
                    "current_rss_bytes": 3_221_225_472,
                    "phase_current_rss_delta_bytes": 1_073_741_824,
                    "lifetime_peak_policy": "AUDIT_ONLY",
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(authority_cli, "RUNS_ROOT", runs_root)
    monkeypatch.setattr(Path, "is_mount", lambda _path: True)
    monkeypatch.setattr(authority_cli, "EXPECTED_RESOLVED_PARTITION_COUNT", 4)
    monkeypatch.setattr(
        authority_cli,
        "EXPECTED_ARCHIVE_COUNTS",
        {
            "BTCUSDT": {"daily_archive_count": 1, "monthly_archive_count": 1},
            "ETHUSDT": {"daily_archive_count": 1, "monthly_archive_count": 1},
        },
    )
    monkeypatch.setattr(
        authority_cli,
        "_git",
        lambda *args: {
            ("rev-parse", "HEAD"): commit,
            ("branch", "--show-current"): authority_cli.APPROVED_BRANCH,
            ("status", "--porcelain", "--untracked-files=all"): "",
            ("rev-parse", "HEAD^{tree}"): "3" * 40,
        }[args],
    )
    monkeypatch.setattr(authority_cli, "compute_v2_code_tree_sha256", lambda _root: tree_sha256)

    def write_component(path: Path, semantic_hash: str) -> SimpleNamespace:
        authority_cli._write_once(path, {"semantic_hash": semantic_hash})
        return SimpleNamespace(manifest_hash=semantic_hash)

    monkeypatch.setattr(
        authority_cli,
        "freeze_contract_price_inventory_manifest",
        lambda **kwargs: write_component(kwargs["output_path"], "4" * 64),
    )

    def write_trades(**kwargs: object) -> SimpleNamespace:
        output_path = kwargs["output_path"]
        assert isinstance(output_path, Path)
        component = write_component(output_path, "5" * 64)
        component.resolved_partition_count = 4
        component.entries = (
            SimpleNamespace(instrument="BTCUSDT", archive_partition="2026-06"),
            SimpleNamespace(instrument="BTCUSDT", archive_partition="2026-07-01"),
            SimpleNamespace(instrument="ETHUSDT", archive_partition="2026-06"),
            SimpleNamespace(instrument="ETHUSDT", archive_partition="2026-07-01"),
        )
        return component

    monkeypatch.setattr(
        authority_cli, "freeze_stage1_resolved_source_index_from_catalog", write_trades
    )

    def write_protection(**kwargs: object) -> tuple[SimpleNamespace, SimpleNamespace]:
        root = kwargs["transition_run_root"]
        assert isinstance(root, Path)
        protection = SimpleNamespace(
            manifest_hash="6" * 64,
            source_run_id=authority_cli.RUN_A_ID,
            catalog_logical_hash="7" * 64,
            catalog_physical_hash="8" * 64,
        )
        authority_cli._write_once(
            root / "manifests" / f"{protection.manifest_hash}.json",
            {"semantic_hash": protection.manifest_hash},
        )
        authority_cli._write_once(
            root / "reports" / "orchestration-supersession.json",
            {"status": "PASS"},
        )
        return SimpleNamespace(), protection

    monkeypatch.setattr(authority_cli, "freeze_run_a_protection", write_protection)

    def write_migration(**kwargs: object) -> SimpleNamespace:
        root = kwargs["transition_run_root"]
        assert isinstance(root, Path)
        migration = SimpleNamespace(manifest_hash="9" * 64)
        authority_cli._write_once(
            root / "manifests" / f"{migration.manifest_hash}.json",
            {"semantic_hash": migration.manifest_hash},
        )
        return migration

    monkeypatch.setattr(authority_cli, "freeze_v2_migration_manifest", write_migration)

    class FakeRuntime:
        manifest_hash = "a" * 64
        snapshot_id = "b" * 64

        def model_dump(self, *, mode: str) -> dict[str, str]:
            assert mode == "json"
            return {"manifest_hash": self.manifest_hash, "snapshot_id": self.snapshot_id}

    monkeypatch.setattr(authority_cli, "build_runtime_v2_manifest", lambda **_kwargs: FakeRuntime())
    argv = [
        "freeze",
        "--transition-run-id",
        transition_id,
        "--destination-run-id",
        destination_id,
        "--quality-evidence",
        str(quality_path),
        "--memory-evidence",
        str(memory_path),
        "--finalization-memory-evidence",
        str(finalization_memory_path),
    ]

    assert authority_cli.main(argv) == 0
    receipt_path = transition_root / "reports" / "authority-bundle-validation.json"
    first = receipt_path.read_bytes()
    assert authority_cli.main(argv) == 0
    receipt = json.loads(receipt_path.read_bytes())

    assert receipt_path.read_bytes() == first
    assert receipt["status"] == "PASS"
    assert receipt["change_request"] == "CR-2026-012"
    assert receipt["superseded_authority_change_requests"] == [
        "CR-2026-009",
        "CR-2026-010",
        "CR-2026-011",
    ]
    assert receipt["authority_bundle_id"].startswith("stage2-v2-authority-bundle-")
    assert receipt["reserved_destination_run_id"] == destination_id
    assert receipt["destination_status"] == "RESERVED_NOT_CREATED"
    assert receipt["archive_partition_counts"] == {
        "BTCUSDT": {"daily_archive_count": 1, "monthly_archive_count": 1},
        "ETHUSDT": {"daily_archive_count": 1, "monthly_archive_count": 1},
    }
    assert set(receipt["components"]) == {
        "contract_price_inventory",
        "orchestration_supersession",
        "runtime_manifest",
        "run_a_protection",
        "stage1_trades_resolved_index",
        "v2_migration_manifest",
    }
    assert not (runs_root / destination_id).exists()
