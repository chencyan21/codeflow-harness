from __future__ import annotations

import argparse
import json
import tarfile
from pathlib import Path
from typing import Any

from _harness_bench_common import ROOT, portable_path, project_path, utc_now_iso
from codeflow.redaction import redact_text


DEFAULT_ARCHIVE_DIR = ROOT / "benchmark" / "artifact_archives"
DEFAULT_MANIFEST_DIR = ROOT / "benchmark" / "artifacts" / "manifests"


def _load_run_manifest(result_dir: Path) -> dict[str, Any]:
    path = result_dir / "run_manifest.json"
    if not path.exists():
        return {"run_id": result_dir.name, "missing_run_manifest": True}
    return json.loads(path.read_text(encoding="utf-8"))


def _iter_files(result_dir: Path) -> list[Path]:
    return sorted(path for path in result_dir.rglob("*") if path.is_file())


def archive_run(result_dir: Path, *, archive_dir: Path, manifest_dir: Path) -> dict[str, Any]:
    result_dir = result_dir.resolve()
    run_manifest = _load_run_manifest(result_dir)
    run_id = str(run_manifest.get("run_id") or result_dir.name)
    archive_dir.mkdir(parents=True, exist_ok=True)
    manifest_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / f"{run_id}.tar.gz"
    files = _iter_files(result_dir)

    with tarfile.open(archive_path, "w:gz") as archive:
        for path in files:
            relative = path.relative_to(result_dir)
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                archive.add(path, arcname=str(relative))
                continue
            temp_path = result_dir / ".codeflow-redacted-archive.tmp"
            temp_path.write_text(redact_text(text), encoding="utf-8")
            archive.add(temp_path, arcname=str(relative))
            temp_path.unlink(missing_ok=True)

    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "created_at": utc_now_iso(),
        "result_dir": portable_path(result_dir),
        "archive": portable_path(archive_path),
        "files": [portable_path(path) for path in files],
        "redacted": True,
    }
    manifest_path = manifest_dir / f"{run_id}.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive and redact a benchmark result directory.")
    parser.add_argument("result_dir", help="Benchmark result directory containing run_manifest.json")
    parser.add_argument("--archive-dir", default=str(DEFAULT_ARCHIVE_DIR))
    parser.add_argument("--manifest-dir", default=str(DEFAULT_MANIFEST_DIR))
    args = parser.parse_args()

    manifest = archive_run(
        project_path(args.result_dir),
        archive_dir=project_path(args.archive_dir),
        manifest_dir=project_path(args.manifest_dir),
    )
    print(f"wrote {manifest['archive']}")
    print(f"wrote {portable_path(project_path(args.manifest_dir) / (manifest['run_id'] + '.json'))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
