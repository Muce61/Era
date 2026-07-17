"""Execute approved CR-2026-006 Run A release, fresh Run B and comparison."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from era100x.research.stage_2.pipelines.candidates.io import atomic_json

ROOT = Path(__file__).resolve().parents[1]
STAGE2_ROOT = Path("/Volumes/FuckingLife/era100x_stage2")
RUN_A = "stage2-g1-full-a-20260716T144233Z-366a541b7956"


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--run-a-supplement", type=Path, required=True)
    result.add_argument("--quality-evidence", type=Path, required=True)
    return result


def _run(*command: str) -> str:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {command}\n{completed.stdout}"
        )
    return completed.stdout.strip()


def _json_command(*command: str) -> dict[str, Any]:
    output = _run(*command)
    return cast(dict[str, Any], json.loads(output.splitlines()[-1]))


def _write_once(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        if json.loads(path.read_text()) != payload:
            raise FileExistsError(f"append-only orchestration artifact exists: {path}")
        return
    atomic_json(path, payload)


def main() -> int:
    args = parser().parse_args()
    head = _run("git", "rev-parse", "HEAD")
    if _run("git", "status", "--porcelain"):
        raise ValueError("CR-2026-006 pipeline requires a clean worktree")
    python = sys.executable
    run_a_root = STAGE2_ROOT / "runs" / RUN_A
    orchestration_root = run_a_root / "reports" / "release-recovery"
    status_path = orchestration_root / f"pipeline-{head}.json"
    try:
        _run(
            python,
            "scripts/run_stage2_group1_candidates.py",
            "release-recovery",
            "--action",
            "prepare",
            "--run-id",
            RUN_A,
            "--supplement",
            str(args.run_a_supplement),
        )
        run_a_release = _json_command(
            python,
            "scripts/run_stage2_group1_candidates.py",
            "release-recovery",
            "--action",
            "run",
            "--run-id",
            RUN_A,
            "--supplement",
            str(args.run_a_supplement),
        )
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        run_b = f"stage2-g1-full-b-{timestamp}-{head[:12]}"
        manifest_result = _json_command(
            python,
            "scripts/freeze_stage2_group1_execution_manifest.py",
            "--quality-evidence",
            str(args.quality_evidence),
        )
        manifest = Path(manifest_result["path"])
        _run(
            python,
            "scripts/run_stage2_group1_candidates.py",
            "preflight",
            "--run-id",
            run_b,
            "--manifest",
            str(manifest),
        )
        active = {
            "schema_name": "stage2-cr-2026-006-active-runs-v1",
            "run_a": RUN_A,
            "run_b": run_b,
            "generator_commit": "366a541b7956030d1a0ea2b5c67b4b30e2154c76",
            "release_tool_commit": head,
        }
        atomic_json(
            STAGE2_ROOT
            / "runs"
            / "stage2-g1-preregistration-v1.0"
            / "reports"
            / "s2-t10-active-runs.json",
            active,
        )
        for instrument in ("BTCUSDT", "ETHUSDT"):
            for variant in ("V1_PRICE", "V1_FLOW"):
                _run(
                    python,
                    "scripts/run_stage2_group1_candidates.py",
                    "run",
                    "--run-id",
                    run_b,
                    "--manifest",
                    str(manifest),
                    "--instrument",
                    instrument,
                    "--variant",
                    variant,
                )
        quality_hash = args.quality_evidence.stem.removeprefix("quality-gate-")
        run_b_supplement = _json_command(
            python,
            "scripts/prepare_stage2_release_supplement.py",
            "--quality-evidence-hash",
            quality_hash,
            "--run-id",
            run_b,
            "--execution-manifest",
            str(STAGE2_ROOT / "runs" / run_b / "manifests" / manifest.name),
        )
        run_b_release = _json_command(
            python,
            "scripts/run_stage2_group1_candidates.py",
            "release-recovery",
            "--action",
            "run",
            "--run-id",
            run_b,
            "--supplement",
            run_b_supplement["path"],
        )
        left = json.loads((run_a_root / "reports" / "release-analysis.json").read_text())
        right_root = STAGE2_ROOT / "runs" / run_b
        right = json.loads((right_root / "reports" / "release-analysis.json").read_text())
        fields = ("catalog_logical_hash", "datasets", "distributions", "finalization", "quality")
        differences = [field for field in fields if left[field] != right[field]]
        comparison = {
            "schema_name": "stage2-cr-2026-006-deterministic-comparison-v1",
            "status": "PASS" if not differences else "FAIL",
            "run_a": RUN_A,
            "run_b": run_b,
            "generator_commit": "366a541b7956030d1a0ea2b5c67b4b30e2154c76",
            "release_tool_commit": head,
            "different_fields": differences,
            "run_a_logical_hash": left["catalog_logical_hash"],
            "run_b_logical_hash": right["catalog_logical_hash"],
        }
        _write_once(right_root / "reports" / "deterministic-comparison.json", comparison)
        if differences:
            raise ValueError(f"Run A/B deterministic mismatch: {differences}")
        result = {
            "status": "PASS",
            "run_a_release": run_a_release,
            "run_b": run_b,
            "run_b_release": run_b_release,
            "comparison": comparison,
        }
        _write_once(status_path, result)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        failure = {
            "status": "FAILED",
            "run_a": RUN_A,
            "release_tool_commit": head,
            "error": repr(exc),
        }
        _write_once(status_path, failure)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
