"""Static-only hotfix; no API restart, merchant changes or third-party requests."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tarfile
from pathlib import Path

from deploy_photo_upload_hotfix import write_atomic

ROOT = Path("/opt/poi-hub")
RELEASE = "hotfix-20261022-photo-format-bank"
BACKUP = ROOT / ".deploy-backups" / RELEASE


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def target(name: str) -> Path:
    path = ROOT / name
    if not name.startswith("frontend/dist/") or path.is_symlink():
        raise RuntimeError("file outside frontend release")
    if not path.resolve().is_relative_to(ROOT / "frontend/dist"):
        raise RuntimeError("invalid path")
    return path


def package() -> None:
    root = Path(__file__).resolve().parents[1]
    releases = root / ".data/releases"
    baseline: dict[str, str] = {}
    for name in [
        "release-20261021-merchant-applyments",
        "hotfix-20261021-photo-upload",
        "release-20261022-deepseek-assistant",
        "hotfix-20261022-photo-format",
    ]:
        baseline.update(json.loads((releases / (name + ".json")).read_text())["files"])
    paths = [path for path in (root / "frontend/dist").rglob("*") if path.is_file()]
    files = {path.relative_to(root).as_posix(): digest(path) for path in paths}
    archive = releases / (RELEASE + ".tar.gz")
    with tarfile.open(archive, "w:gz") as bundle:
        for path in paths:
            if path.is_symlink():
                raise RuntimeError("symlink in package")
            bundle.add(path, arcname=path.relative_to(root).as_posix(), recursive=False)
    manifest = {
        "files": files,
        "before": {name: baseline.get(name) for name in files},
        "sha256": digest(archive),
    }
    (releases / (RELEASE + ".json")).write_text(json.dumps(manifest, indent=2))
    print(json.dumps({"release": RELEASE, "files": len(files), "sha256": manifest["sha256"]}))


def publish() -> None:
    if BACKUP.exists():
        raise RuntimeError("backup already exists")
    archive = ROOT / ".deploy-backups" / (RELEASE + ".tar.gz")
    manifest = json.loads((ROOT / ".deploy-backups" / (RELEASE + ".json")).read_text())
    if digest(archive) != manifest["sha256"]:
        raise RuntimeError("archive checksum mismatch")
    for name, before in manifest["before"].items():
        path = target(name)
        if (digest(path) if path.is_file() else None) != before:
            raise RuntimeError("baseline changed: " + name)
    env_digest = digest(ROOT / ".env")
    BACKUP.mkdir(mode=0o700)
    os.chmod(BACKUP, 0o700)
    stage = BACKUP / "stage"
    stage.mkdir(mode=0o700)
    with tarfile.open(archive) as bundle:
        members = bundle.getmembers()
        if len(members) != len(manifest["files"]) or {m.name for m in members} != set(
            manifest["files"]
        ):
            raise RuntimeError("unexpected members")
        for member in members:
            target(member.name)
            if not member.isfile():
                raise RuntimeError("invalid archive member")
            content = bundle.extractfile(member)
            if content is None:
                raise RuntimeError("missing file")
            destination = stage / member.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content.read())
            if digest(destination) != manifest["files"][member.name]:
                raise RuntimeError("staged checksum mismatch")
    with tarfile.open(BACKUP / "files-before.tar.gz", "w:gz") as bundle:
        for name in manifest["files"]:
            if target(name).is_file():
                bundle.add(target(name), arcname=name, recursive=False)
    (BACKUP / "manifest.json").write_text(json.dumps(manifest))
    try:
        for name in sorted(manifest["files"], key=lambda name: name == "frontend/dist/index.html"):
            write_atomic(target(name), (stage / name).read_bytes())
        if digest(ROOT / ".env") != env_digest:
            raise RuntimeError("environment changed")
        for name, expected in manifest["files"].items():
            if digest(target(name)) != expected:
                raise RuntimeError("published checksum mismatch")
    except Exception:
        with tarfile.open(BACKUP / "files-before.tar.gz") as bundle:
            for name, before in manifest["before"].items():
                if before is not None:
                    content = bundle.extractfile(name)
                    if content is None:
                        raise RuntimeError("rollback source missing")
                    write_atomic(target(name), content.read())
        # New hashed assets are harmless and deliberately retained on rollback.
        raise
    print(
        json.dumps(
            {
                "release": RELEASE,
                "deployed": True,
                "backend_unchanged": True,
                "environment_unchanged": True,
                "backup": str(BACKUP),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["package", "publish"])
    try:
        package() if parser.parse_args().action == "package" else publish()
    except Exception as error:
        print(json.dumps({"failed": True, "error": str(error)}), flush=True)
        raise SystemExit(1) from None
