"""Append-only repositories for Stage 2 manifests."""

from __future__ import annotations

from pathlib import Path

from .models import (
    Stage2ExecutionManifest,
    Stage2PreregistrationManifest,
    Stage2ReleaseSupplementManifest,
    canonical_json,
)

Manifest = Stage2PreregistrationManifest | Stage2ExecutionManifest | Stage2ReleaseSupplementManifest


class AppendOnlyManifestRepository:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)

    def publish(self, manifest: Manifest) -> Path:
        path = self.directory / f"{manifest.manifest_hash}.json"
        content = canonical_json(manifest.model_dump(mode="python")) + "\n"
        if path.exists():
            if path.read_text(encoding="utf-8") != content:
                raise FileExistsError("immutable manifest hash collision")
            return path
        with path.open("x", encoding="utf-8") as stream:
            stream.write(content)
        return path
