"""Small photo-upload release; preserves the live submission flag and all data."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

RELEASE = "hotfix-20261021-photo-upload"
ROOT = Path("/opt/poi-hub")
BACKUP = ROOT / ".deploy-backups" / RELEASE
NGINX = Path("/etc/nginx/sites-available/poi-hub")
SOURCE_FILES = [
    "backend/poi_admin/merchant_applyments/limits.py",
    "backend/poi_admin/merchant_applyments/service.py",
    "backend/poi_admin/merchant_applyments/schemas.py",
    "backend/poi_admin/merchant_applyments/router.py",
]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def package() -> None:
    root = Path(__file__).resolve().parents[1]
    releases = root / ".data/releases"
    old = json.loads((releases / "release-20261021-merchant-applyments.json").read_text())
    files = [root / name for name in SOURCE_FILES]
    files += [path for path in (root / "frontend/dist").rglob("*") if path.is_file()]
    hashes = {path.relative_to(root).as_posix(): digest(path) for path in files}
    archive = releases / (RELEASE + ".tar.gz")
    with tarfile.open(archive, "w:gz") as bundle:
        for path in files:
            if path.is_symlink():
                raise RuntimeError("symlink in hotfix")
            bundle.add(path, arcname=path.relative_to(root).as_posix(), recursive=False)
    manifest = {
        "files": hashes,
        "before": {name: old["files"].get(name) for name in hashes},
        "sha256": digest(archive),
    }
    (releases / (RELEASE + ".json")).write_text(json.dumps(manifest, indent=2))
    print(json.dumps({"release": RELEASE, "sha256": manifest["sha256"], "files": len(files)}))


def run(args: list[str]) -> None:
    result = subprocess.run(args, cwd=ROOT, capture_output=True)
    if result.returncode:
        raise RuntimeError("command failed: " + Path(args[0]).name)


def target(name: str) -> Path:
    path = ROOT / name
    if path.is_symlink() or not path.resolve().is_relative_to(ROOT):
        raise RuntimeError("invalid hotfix path")
    if name not in SOURCE_FILES and not name.startswith("frontend/dist/"):
        raise RuntimeError("file outside hotfix scope")
    return path


def write_atomic(path: Path, data: bytes) -> None:
    info = path.stat() if path.exists() else None
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".photo-hotfix")
    with temporary.open("wb") as stream:
        stream.write(data)
    os.chmod(temporary, info.st_mode & 0o777 if info else 0o644)
    if info:
        os.chown(temporary, info.st_uid, info.st_gid)
    os.replace(temporary, path)


def ready() -> None:
    for _ in range(90):
        try:
            with urllib.request.urlopen(
                "http://127.0.0.1:8000/api/v1/health/ready", timeout=2
            ) as result:
                if result.status == 200:
                    return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("API not ready")


async def no_active_submissions() -> None:
    from sqlalchemy import text

    from poi_admin.core.config import get_settings
    from poi_admin.core.database import create_database

    settings = get_settings()
    if settings.environment != "production" or not settings.wechat_applyment_submit_enabled:
        raise RuntimeError("unexpected live environment or submission flag")
    db = create_database(settings)
    try:
        async with db.session_factory() as session:
            count = (
                await session.execute(
                    text("select count(*) from merchant_applyments where state='submitting'")
                )
            ).scalar_one()
            if count:
                raise RuntimeError("wait for active merchant submission before restart")
    finally:
        await db.dispose()


def publish() -> None:
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT / "backend"))
    asyncio.run(no_active_submissions())
    if BACKUP.exists():
        raise RuntimeError("hotfix backup already exists")
    package_path = ROOT / ".deploy-backups" / (RELEASE + ".tar.gz")
    manifest = json.loads((ROOT / ".deploy-backups" / (RELEASE + ".json")).read_text())
    if digest(package_path) != manifest["sha256"]:
        raise RuntimeError("archive checksum mismatch")
    for name, expected in manifest["before"].items():
        path = target(name)
        actual = digest(path) if path.is_file() else None
        if actual != expected:
            raise RuntimeError("live file changed since baseline: " + name)
    nginx_before = NGINX.read_bytes()
    if nginx_before.count(b"client_max_body_size 2m;") != 1:
        raise RuntimeError("unexpected SaaS proxy configuration")
    config_digest = digest(ROOT / ".env")
    BACKUP.mkdir(mode=0o700)
    os.chmod(BACKUP, 0o700)
    stage = BACKUP / "stage"
    stage.mkdir(mode=0o700)
    with tarfile.open(package_path) as bundle:
        members = bundle.getmembers()
        if {item.name for item in members} != set(manifest["files"]):
            raise RuntimeError("unexpected archive members")
        for member in members:
            if not member.isfile():
                raise RuntimeError("non-file archive entry")
            target(member.name)
            destination = stage / member.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            content = bundle.extractfile(member)
            if content is None:
                raise RuntimeError("missing archive file")
            destination.write_bytes(content.read())
            if digest(destination) != manifest["files"][member.name]:
                raise RuntimeError("staged file mismatch")
    with tarfile.open(BACKUP / "files-before.tar.gz", "w:gz") as bundle:
        for name in manifest["files"]:
            if target(name).is_file():
                bundle.add(target(name), arcname=name, recursive=False)
    (BACKUP / "nginx-before.conf").write_bytes(nginx_before)
    (BACKUP / "manifest.json").write_text(json.dumps(manifest))
    stopped = False
    changed = False
    try:
        run(["systemctl", "stop", "poi-hub-api"])
        stopped = True
        asyncio.run(no_active_submissions())
        changed = True
        for name in sorted(manifest["files"], key=lambda name: name == "frontend/dist/index.html"):
            write_atomic(target(name), (stage / name).read_bytes())
        write_atomic(
            NGINX, nginx_before.replace(b"client_max_body_size 2m;", b"client_max_body_size 5m;")
        )
        run(["nginx", "-t"])
        if digest(ROOT / ".env") != config_digest:
            raise RuntimeError("runtime configuration changed")
        run(["systemctl", "start", "poi-hub-api"])
        ready()
        run(["systemctl", "reload", "nginx"])
        run(["systemctl", "is-active", "poi-hub-api", "poi-hub-worker", "nginx", "x-ui"])
        for name, expected in manifest["files"].items():
            if digest(target(name)) != expected:
                raise RuntimeError("published file mismatch")
        print(
            json.dumps(
                {
                    "hotfix": RELEASE,
                    "deployed": True,
                    "max_image_bytes": 5 * 1024 * 1024,
                    "nginx_limit": "5m",
                    "environment_unchanged": True,
                    "real_submission_still_enabled": True,
                    "backup": str(BACKUP),
                }
            ),
            flush=True,
        )
    except Exception:
        if changed:
            run(["systemctl", "stop", "poi-hub-api"])
            with tarfile.open(BACKUP / "files-before.tar.gz") as bundle:
                for name, original in manifest["before"].items():
                    path = target(name)
                    if original is None:
                        if path.is_file() and digest(path) == manifest["files"][name]:
                            path.unlink()
                    else:
                        content = bundle.extractfile(name)
                        if content is None:
                            raise RuntimeError("rollback source missing")
                        write_atomic(path, content.read())
            write_atomic(NGINX, nginx_before)
            run(["nginx", "-t"])
            run(["systemctl", "reload", "nginx"])
        if stopped:
            run(["systemctl", "start", "poi-hub-api"])
            ready()
        print(json.dumps({"hotfix_rolled_back": True}), flush=True)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["package", "publish"])
    action = parser.parse_args().action
    try:
        package() if action == "package" else publish()
    except Exception as error:
        print(json.dumps({"failed": True, "error": str(error)}), flush=True)
        raise SystemExit(1) from None
