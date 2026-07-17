from __future__ import annotations

import pytest

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
        ]
    )
    assert authorities.destination_run_id == "stage2-g1-v2-b-test"
    with pytest.raises(SystemExit):
        authority_parser().parse_args(
            [
                "--transition-run-id",
                "stage2-g1-v2-authority-test",
                "--destination-run-id",
                "stage2-g1-v2-b-test",
                "--quality-evidence",
                "/Volumes/FuckingLife/era100x_stage2/runs/evidence.json",
                "--instrument",
                "BTCUSDT",
            ]
        )
