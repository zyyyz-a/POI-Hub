"""Release only the assistant; no merchant writes, credentials or migrations."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import tarfile
from pathlib import Path

from deploy_photo_upload_hotfix import no_active_submissions, ready, run, write_atomic

RELEASE = "release-20261022-deepseek-assistant"
ROOT = Path("/opt/poi-hub")
BACKUP = ROOT / ".deploy-backups" / RELEASE
SOURCES = {
    "backend/poi_admin/main.py",
    "backend/poi_admin/core/config.py",
    "backend/poi_admin/assistant/__init__.py",
    "backend/poi_admin/assistant/knowledge.py",
    "backend/poi_admin/assistant/service.py",
    "backend/poi_admin/assistant/router.py",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def target(name: str) -> Path:
    path = ROOT / name
    if name not in SOURCES and not name.startswith("frontend/dist/"):
        raise RuntimeError("file outside assistant release")
    if path.is_symlink() or not path.resolve().is_relative_to(ROOT):
        raise RuntimeError("invalid release path")
    return path


def package() -> None:
    root = Path(__file__).resolve().parents[1]
    releases = root / ".data/releases"
    baseline: dict[str, str] = {}
    for name in ["release-20261021-merchant-applyments", "hotfix-20261021-photo-upload"]:
        baseline.update(json.loads((releases / (name + ".json")).read_text())["files"])
    paths = [root / name for name in sorted(SOURCES)]
    paths += [path for path in (root / "frontend/dist").rglob("*") if path.is_file()]
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
    import pwd

    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT / "backend"))
    asyncio.run(no_active_submissions())
    if BACKUP.exists():
        raise RuntimeError("release backup already exists")
    archive = ROOT / ".deploy-backups" / (RELEASE + ".tar.gz")
    manifest = json.loads((ROOT / ".deploy-backups" / (RELEASE + ".json")).read_text())
    if digest(archive) != manifest["sha256"]:
        raise RuntimeError("archive checksum mismatch")
    for name, expected in manifest["before"].items():
        path = target(name)
        if (digest(path) if path.is_file() else None) != expected:
            raise RuntimeError("live baseline changed: " + name)
    env_hash = digest(ROOT / ".env")
    nginx_path = Path("/etc/nginx/sites-available/poi-hub")
    nginx_hash = digest(nginx_path)
    BACKUP.mkdir(mode=0o700)
    os.chmod(BACKUP, 0o700)
    stage = BACKUP / "stage"
    stage.mkdir(mode=0o700)
    with tarfile.open(archive) as bundle:
        members = bundle.getmembers()
        if len(members) != len(manifest["files"]) or {m.name for m in members} != set(
            manifest["files"]
        ):
            raise RuntimeError("invalid package members")
        for member in members:
            target(member.name)
            if not member.isfile():
                raise RuntimeError("non-file member")
            content = bundle.extractfile(member)
            if content is None:
                raise RuntimeError("missing source")
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
    changed = False
    stopped = False
    try:
        run(["systemctl", "stop", "poi-hub-api"])
        stopped = True
        asyncio.run(no_active_submissions())
        account = pwd.getpwnam("poi")
        for directory in [ROOT / ".data", ROOT / ".data/assistant"]:
            if directory.is_symlink():
                raise RuntimeError("unsafe settings directory")
            if not directory.exists():
                directory.mkdir(mode=0o700)
                os.chown(directory, account.pw_uid, account.pw_gid)
        changed = True
        for name in sorted(
            manifest["files"], key=lambda value: value == "frontend/dist/index.html"
        ):
            write_atomic(target(name), (stage / name).read_bytes())
        if digest(ROOT / ".env") != env_hash or digest(nginx_path) != nginx_hash:
            raise RuntimeError("unrelated configuration changed")
        run(["systemctl", "start", "poi-hub-api"])
        ready()
        run(["systemctl", "is-active", "poi-hub-api", "poi-hub-worker", "nginx", "x-ui"])
        for name, expected in manifest["files"].items():
            if digest(target(name)) != expected:
                raise RuntimeError("published checksum mismatch")
        print(
            json.dumps(
                {
                    "release": RELEASE,
                    "deployed": True,
                    "environment_unchanged": True,
                    "merchant_data_unchanged": True,
                    "submission_still_enabled": True,
                    "key_configured": (ROOT / ".data/assistant/deepseek.enc").is_file(),
                    "backup": str(BACKUP),
                }
            ),
            flush=True,
        )
    except Exception:
        if changed:
            run(["systemctl", "stop", "poi-hub-api"])
            with tarfile.open(BACKUP / "files-before.tar.gz") as bundle:
                for name, previous in manifest["before"].items():
                    path = target(name)
                    if previous is None:
                        if path.is_file() and digest(path) == manifest["files"][name]:
                            path.unlink()
                    else:
                        content = bundle.extractfile(name)
                        if content is None:
                            raise RuntimeError("rollback source missing")
                        write_atomic(path, content.read())
        if stopped:
            run(["systemctl", "start", "poi-hub-api"])
            ready()
        print(json.dumps({"rolled_back": True}), flush=True)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["package", "publish"])
    try:
        package() if parser.parse_args().action == "package" else publish()
    except Exception as error:
        print(json.dumps({"failed": True, "error": str(error)}), flush=True)
        raise SystemExit(1) from None
