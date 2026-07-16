"""Create append-only CR-2026-005 bounded replay evidence; never publish full-run data."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import date
from pathlib import Path
from typing import Any

from era100x.research.stage_2.manifests.models import Stage2PreregistrationManifest
from era100x.research.stage_2.pipelines.candidates.candidate_finalizer import (
    finalize_candidate_attempts,
)
from era100x.research.stage_2.pipelines.candidates.io import records_logical_hash
from era100x.research.stage_2.pipelines.candidates.price_phase import build_price_day
from era100x.research.stage_2.pipelines.candidates.runner import (
    CONTRACT_ROOT,
    EXPECTED_CONFIG_HASH,
    EXPECTED_PREREGISTRATION_MANIFEST,
    FAILED_RUN_ID,
    LOGICAL_HASHES,
    PREREGISTRATION_MANIFEST_PATH,
    STAGE1_RUN_ID,
)

FAILED_V15_RUN_ID = "stage2-g1-full-a-20260716T122601Z-0247d30f9f62"
TARGET_DAYS = (date(2020, 4, 27), date(2020, 4, 28))
CONFLICT_IDS = (
    "377ea4c8ffdc02098644e5d32e8f5f6e1cde52bb3203baf080e74830987ca617",
    "a5590255f745e9c3133d29108f1572fc78acc4a9de78aa540d8f3edbb47f9d07",
)


def _sha256_json(payload: Any) -> str:
    rendered = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _assert_head(code_commit: str) -> None:
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if head != code_commit:
        raise ValueError("diagnostic code commit does not match HEAD")


def _assert_frozen_inputs(stage2_root: Path, code_commit: str) -> dict[str, Any]:
    _assert_head(code_commit)
    tag_commit = subprocess.check_output(
        ["git", "rev-parse", "stage-1-v1.0-passed^{commit}"], text=True
    ).strip()
    if tag_commit != "b7d4ff3d18dcfc515feb8892659cb0b186cd68f8":
        raise ValueError("Stage 1 tag changed")
    preregistration = Stage2PreregistrationManifest.model_validate_json(
        PREREGISTRATION_MANIFEST_PATH.read_bytes()
    )
    if preregistration.manifest_hash != EXPECTED_PREREGISTRATION_MANIFEST:
        raise ValueError("Stage 2 preregistration hash changed")
    if preregistration.config_hash != EXPECTED_CONFIG_HASH:
        raise ValueError("Stage 2 config hash changed")
    failed_root = stage2_root / "runs" / FAILED_V15_RUN_ID
    checkpoint = json.loads((failed_root / "checkpoint.json").read_text())
    if checkpoint.get("status") != "FAILED_UNPUBLISHED":
        raise ValueError("failed v1.5 run state changed")
    if (failed_root / "published" / "data").exists():
        raise ValueError("failed v1.5 run was published")
    conflict_path = (
        failed_root / "reports/candidate_identity_conflicts/instrument=BTCUSDT/variant=V1_PRICE/"
        "date=2020-04-27.json"
    )
    conflict = json.loads(conflict_path.read_text())
    observed_ids = tuple(sorted(item["canonical_candidate_id"] for item in conflict["conflicts"]))
    if observed_ids != tuple(sorted(CONFLICT_IDS)):
        raise ValueError("retained conflict evidence changed")
    return {
        "stage1_tag_commit": tag_commit,
        "stage1_data_run_id": STAGE1_RUN_ID,
        "stage1_btc_logical_hash": LOGICAL_HASHES["BTCUSDT"],
        "preregistration_hash": preregistration.manifest_hash,
        "config_hash": preregistration.config_hash,
        "audit_of_run_id": FAILED_V15_RUN_ID,
        "predecessor_failure_run_id": FAILED_RUN_ID,
        "retained_conflict_report_sha256": hashlib.sha256(conflict_path.read_bytes()).hexdigest(),
        "retained_conflicts": conflict["conflicts"],
    }


def _replay(days: tuple[date, ...], code_commit: str) -> dict[str, Any]:
    outputs: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for day in days:
        outputs[day.isoformat()] = build_price_day(
            contract_root=CONTRACT_ROOT,
            instrument="BTCUSDT",
            day=day,
            data_run_id=STAGE1_RUN_ID,
            dataset_logical_hash=LOGICAL_HASHES["BTCUSDT"],
            config_hash=EXPECTED_CONFIG_HASH,
            code_version=code_commit,
        )
    daily: dict[str, Any] = {}
    attempts: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for day_key in sorted(outputs):
        datasets: dict[str, Any] = {}
        for dataset, records in sorted(outputs[day_key].items()):
            counts[dataset] = counts.get(dataset, 0) + len(records)
            datasets[dataset] = {
                "count": len(records),
                "logical_hash": records_logical_hash(records, dataset),
            }
            if dataset == "candidate_attempts":
                attempts.extend(records)
        daily[day_key] = datasets
    finalized = finalize_candidate_attempts(attempts)
    candidate_rows = sorted(
        (
            str(row["canonical_candidate_id"]),
            str(row["canonical_payload_hash"]),
            str(row["source_processing_partition"]),
            int(row["source_row_ordinal"]),
        )
        for row in attempts
    )
    selected_conflicts = {
        candidate_id: [row for row in candidate_rows if row[0] == candidate_id]
        for candidate_id in CONFLICT_IDS
    }
    for candidate_id, rows in selected_conflicts.items():
        if len(rows) != 1:
            raise ValueError(f"conflict candidate does not have one owner attempt: {candidate_id}")
    semantic = {
        "target_days": [day.isoformat() for day in TARGET_DAYS],
        "daily": daily,
        "counts": dict(sorted(counts.items())),
        "candidate_id_set_hash": _sha256_json(sorted({row[0] for row in candidate_rows})),
        "candidate_payload_set_hash": _sha256_json(
            sorted({(row[0], row[1]) for row in candidate_rows})
        ),
        "candidate_attempt_count": len(candidate_rows),
        "candidate_id_count": len({row[0] for row in candidate_rows}),
        "identity_conflict_count": finalized.summary["identity_conflict_count"],
        "exact_duplicate_excluded_count": finalized.summary["exact_duplicate_excluded_count"],
        "selected_original_conflicts": selected_conflicts,
    }
    return {**semantic, "replay_logical_hash": _sha256_json(semantic)}


def create_evidence(*, stage2_root: Path, output_root: Path, code_commit: str) -> dict[str, Any]:
    if output_root.exists():
        raise FileExistsError(f"append-only diagnostic evidence exists: {output_root}")
    baseline = _assert_frozen_inputs(stage2_root, code_commit)
    replay_a = _replay(TARGET_DAYS, code_commit)
    replay_b = _replay(tuple(reversed(TARGET_DAYS)), code_commit)
    if replay_a != replay_b:
        raise ValueError("CR-2026-005 dual replay is not deterministic")
    if replay_a["identity_conflict_count"] != 0:
        raise ValueError("CR-2026-005 replay still has identity conflicts")
    for name in ("staging", "published", "manifests", "reports", "logs", "tmp"):
        (output_root / name).mkdir(parents=True, exist_ok=False)
    summary = {
        "schema": "cr-2026-005-diagnostic-summary-v1",
        "status": "PASS",
        "code_commit": code_commit,
        "warmup_date": "2020-04-26",
        "published_data": False,
        "baseline": baseline,
        "replay_a": replay_a,
        "replay_b": replay_b,
        "dual_replay_match": True,
    }
    summary_path = output_root / "reports" / "summary.json"
    summary_path.write_text(json.dumps(summary, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "schema": "cr-2026-005-diagnostic-manifest-v1",
        "code_commit": code_commit,
        "audit_of_run_id": FAILED_V15_RUN_ID,
        "stage1_data_run_id": STAGE1_RUN_ID,
        "preregistration_hash": EXPECTED_PREREGISTRATION_MANIFEST,
        "config_hash": EXPECTED_CONFIG_HASH,
        "summary_sha256": hashlib.sha256(summary_path.read_bytes()).hexdigest(),
        "replay_logical_hash": replay_a["replay_logical_hash"],
    }
    manifest["manifest_hash"] = _sha256_json(manifest)
    (output_root / "manifests" / f"{manifest['manifest_hash']}.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    return {**summary, "diagnostic_manifest_hash": manifest["manifest_hash"]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage2-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--code-commit", required=True)
    args = parser.parse_args()
    result = create_evidence(
        stage2_root=args.stage2_root,
        output_root=args.output_root,
        code_commit=args.code_commit,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
