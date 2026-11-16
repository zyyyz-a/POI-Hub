"""Scoped SaaS release: package locally; back up, rehearse, then publish on Linux.

Never creates users, sends merchant applications, calls WeChat, or enables payments.
Private configuration/database backups stay on the server with root-only access.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
import tomllib
from pathlib import Path

RELEASE = "release-20261021-merchant-applyments"
BEFORE = "0021_platform_products"
AFTER = "0022_merchant_applyments"
ROOT = Path("/opt/poi-hub")
BACKUP = ROOT / ".deploy-backups" / RELEASE
STAGE = ROOT / ".deploy-staging" / RELEASE
CLONE = "poi_verify_20261021_applyments"
SOURCES = ["backend", "migrations", "frontend/dist", "alembic.ini", "pyproject.toml", "uv.lock"]
COUNTS = [
    "users",
    "tenants",
    "stores",
    "wechat_connections",
    "direct_orders",
    "merchant_payment_profiles",
    "integration_operations",
    "webhook_events",
]
IDENTITY_QUERIES = {
    "users": "select id,email,password_hash,status,is_platform_admin from users order by id",
    "connections": "select id,capability,mode,app_id,merchant_id,encrypted_secrets "
    "from wechat_connections order by id",
    "payments": "select id,store_id,mode,status,verified,mchid,sp_mchid,sub_mchid "
    "from merchant_payment_profiles order by id",
    "programs": "select id,app_id,status,callback_configured "
    "from platform_mini_programs order by id",
    "bindings": "select id,store_id,store_code,status,discoverable,tencent_poi_id "
    "from mini_program_store_bindings order by id",
}


def emit(phase: str, **data: object) -> None:
    print(json.dumps({"phase": phase, **data}, ensure_ascii=False), flush=True)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_private(path: Path, data: bytes) -> None:
    with path.open("wb") as stream:
        os.chmod(path, 0o600)
        stream.write(data)


def scoped(path: Path, parent: Path) -> Path:
    resolved = path.resolve()
    if path.is_symlink() or not resolved.is_relative_to(parent.resolve()) or resolved == parent:
        raise RuntimeError("path outside deployment scope")
    return resolved


def package() -> None:
    root = Path(__file__).resolve().parents[1]
    output = root / ".data" / "releases"
    output.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    for name in SOURCES + ["docs/merchant-applyment-runbook.md"]:
        item = root / name
        if item.is_dir():
            files.extend(
                path
                for path in item.rglob("*")
                if path.is_file()
                and "__pycache__" not in path.parts
                and (name == "frontend/dist" or path.suffix == ".py")
            )
        else:
            files.append(item)
    manifest = {path.relative_to(root).as_posix(): sha(path) for path in sorted(files)}
    if "migrations/versions/0022_merchant_applyments.py" not in manifest:
        raise RuntimeError("new migration missing")
    archive = output / (RELEASE + ".tar.gz")
    with tarfile.open(archive, "w:gz") as bundle:
        for path in sorted(files):
            if path.is_symlink():
                raise RuntimeError("symlink in release")
            bundle.add(path, arcname=path.relative_to(root).as_posix(), recursive=False)
    (output / (RELEASE + ".json")).write_text(
        json.dumps({"release": RELEASE, "sha256": sha(archive), "files": manifest}, indent=2),
        encoding="utf-8",
    )
    emit("packaged", path=str(archive), sha256=sha(archive), files=len(manifest))


def command(
    args: list[str],
    *,
    env: dict[str, str] | None = None,
    cwd: Path = ROOT,
    output: Path | None = None,
) -> str:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    if output:
        with output.open("wb") as stream:
            os.chmod(output, 0o600)
            result = subprocess.run(
                args, cwd=cwd, env=merged, stdout=stream, stderr=subprocess.PIPE
            )
        stdout = ""
    else:
        result = subprocess.run(args, cwd=cwd, env=merged, capture_output=True)
        stdout = result.stdout.decode("utf-8", errors="replace")
    if BACKUP.exists():
        with (BACKUP / "commands.log").open("ab") as log:
            os.chmod(BACKUP / "commands.log", 0o600)
            log.write(result.stderr)
    if result.returncode:
        raise RuntimeError("deployment command failed: " + Path(args[0]).name)
    return stdout


def database_env(url: object, database: str | None = None) -> dict[str, str]:
    return {
        "PGHOST": url.host or "127.0.0.1",
        "PGPORT": str(url.port or 5432),
        "PGUSER": url.username or "",
        "PGPASSWORD": url.password or "",
        "PGDATABASE": database or url.database or "",
        "PGCONNECT_TIMEOUT": "10",
        "PGSSLMODE": str(url.query.get("sslmode", "prefer")),
    }


async def snapshot(database_url: str) -> dict[str, object]:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            counts = {}
            fingerprints = {}
            for table in COUNTS:
                counts[table] = (
                    await connection.execute(text("select count(*) from " + table))
                ).scalar_one()
            for label, sql in IDENTITY_QUERIES.items():
                rows = (await connection.execute(text(sql))).all()
                encoded = json.dumps(
                    [list(row) for row in rows], default=str, sort_keys=True
                ).encode()
                fingerprints[label] = hashlib.sha256(encoded).hexdigest()
            revision = (
                await connection.execute(text("select version_num from alembic_version"))
            ).scalar_one()
            return {"counts": counts, "fingerprints": fingerprints, "revision": revision}
    finally:
        await engine.dispose()


def load_runtime():
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT / "backend"))
    from sqlalchemy.engine import make_url

    from poi_admin.core.config import get_settings

    settings = get_settings()
    url = make_url(settings.database_url)
    if settings.environment != "production" or url.get_backend_name() != "postgresql":
        raise RuntimeError("unexpected deployment environment")
    if url.host not in {"localhost", "127.0.0.1", None} or (url.port or 5432) != 5432:
        raise RuntimeError("unexpected database cluster")
    return settings, url


def clone_url(url: object) -> str:
    return url.set(database=CLONE).render_as_string(hide_password=False)


def prepare(archive: Path, manifest_path: Path) -> None:
    if ROOT.resolve() != ROOT or BACKUP.exists() or STAGE.exists():
        raise RuntimeError("release directory already exists or root changed")
    settings, url = load_runtime()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["release"] != RELEASE or sha(archive) != manifest["sha256"]:
        raise RuntimeError("release checksum mismatch")
    current = asyncio.run(snapshot(settings.database_url))
    if current["revision"] != BEFORE:
        raise RuntimeError("unexpected current migration revision")
    for name in ("pyproject.toml", "uv.lock"):
        # Semantic dependency equality is checked below after staging.
        if not (ROOT / name).is_file():
            raise RuntimeError("runtime dependency manifest missing")
    BACKUP.mkdir(parents=True, mode=0o700)
    os.chmod(BACKUP, 0o700)
    STAGE.mkdir(parents=True, mode=0o700)
    os.chmod(STAGE, 0o700)
    with tarfile.open(archive, "r:gz") as bundle:
        names = set()
        for member in bundle.getmembers():
            if not member.isfile() or member.name not in manifest["files"] or member.name in names:
                raise RuntimeError("unexpected archive entry")
            destination = scoped(STAGE / member.name, STAGE)
            destination.parent.mkdir(parents=True, exist_ok=True)
            source = bundle.extractfile(member)
            if source is None:
                raise RuntimeError("missing archive content")
            destination.write_bytes(source.read())
            if sha(destination) != manifest["files"][member.name]:
                raise RuntimeError("staged file checksum mismatch")
            names.add(member.name)
        if names != set(manifest["files"]):
            raise RuntimeError("archive incomplete")
    if tomllib.loads((ROOT / "pyproject.toml").read_text()) != tomllib.loads(
        (STAGE / "pyproject.toml").read_text()
    ):
        raise RuntimeError("dependency manifest changed; explicit installation required")
    if (ROOT / "uv.lock").read_bytes() != (STAGE / "uv.lock").read_bytes():
        raise RuntimeError("lockfile changed")
    originals = {}
    with tarfile.open(BACKUP / "source-before.tar.gz", "w:gz") as bundle:
        for name in SOURCES:
            bundle.add(ROOT / name, arcname=name)
        for name in manifest["files"]:
            if name.startswith("docs/") and (ROOT / name).is_file():
                bundle.add(ROOT / name, arcname=name, recursive=False)
        for name in manifest["files"]:
            path = scoped(ROOT / name, ROOT)
            originals[name] = sha(path) if path.is_file() else None
    os.chmod(BACKUP / "source-before.tar.gz", 0o600)
    write_private(BACKUP / "environment-before", (ROOT / ".env").read_bytes())
    write_private(BACKUP / "baseline.json", json.dumps(current).encode())
    write_private(BACKUP / "manifest.json", json.dumps(manifest).encode())
    write_private(BACKUP / "originals.json", json.dumps(originals).encode())
    command(
        ["pg_dump", "--format=custom", "--no-password"],
        env=database_env(url),
        output=BACKUP / "database-rehearsal.dump",
    )
    command(["pg_restore", "--list", str(BACKUP / "database-rehearsal.dump")])
    emit("backup_complete", backup=str(BACKUP))
    # A separate database is never connected to a running app or worker.
    command(
        [
            "runuser",
            "-u",
            "postgres",
            "--",
            "createdb",
            "--template=template0",
            "--owner=" + str(url.username),
            CLONE,
        ]
    )
    command(
        [
            "pg_restore",
            "--no-password",
            "--no-owner",
            "--no-acl",
            "--exit-on-error",
            "--dbname=" + CLONE,
            str(BACKUP / "database-rehearsal.dump"),
        ],
        env=database_env(url, CLONE),
    )
    restored = asyncio.run(snapshot(clone_url(url)))
    if restored != current:
        raise RuntimeError("restored database does not match backup baseline")
    command(
        [str(ROOT / ".venv/bin/python"), "-m", "alembic", "upgrade", "head"],
        env={"DATABASE_URL": clone_url(url), "PYTHONPATH": str(STAGE / "backend")},
        cwd=STAGE,
    )
    migrated = asyncio.run(snapshot(clone_url(url)))
    if migrated["revision"] != AFTER or migrated["fingerprints"] != current["fingerprints"]:
        raise RuntimeError("rehearsal migration altered protected records")
    command([str(ROOT / ".venv/bin/python"), "-m", "compileall", "-q", str(STAGE / "backend")])
    write_private(
        BACKUP / "prepared.json", json.dumps({"verified": True, "revision": AFTER}).encode()
    )
    emit("rehearsal_passed", restored=True, migration=AFTER, protected_records_unchanged=True)


def replace_file(source: Path, target: Path, *, mode: int = 0o644) -> None:
    import pwd

    target = scoped(target, ROOT)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".deploy-" + RELEASE)
    scoped(temporary, ROOT)
    shutil.copyfile(source, temporary)
    os.chmod(temporary, mode)
    owner = pwd.getpwnam("poi")
    os.chown(temporary, owner.pw_uid, owner.pw_gid)
    os.replace(temporary, target)


def health() -> None:
    import urllib.request

    for _ in range(90):
        try:
            with urllib.request.urlopen(
                "http://127.0.0.1:8000/api/v1/health/ready", timeout=2
            ) as result:
                if result.status == 200 and json.load(result).get("status") == "ok":
                    return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("API readiness did not recover")


def publish() -> None:
    import fcntl

    settings, url = load_runtime()
    if not (BACKUP / "prepared.json").is_file():
        raise RuntimeError("rehearsal required")
    if (ROOT / ".env").read_bytes() != (BACKUP / "environment-before").read_bytes():
        raise RuntimeError("production configuration changed since preparation")
    manifest = json.loads((BACKUP / "manifest.json").read_text())
    originals = json.loads((BACKUP / "originals.json").read_text())
    for name, digest in originals.items():
        path = scoped(ROOT / name, ROOT)
        if (sha(path) if path.is_file() else None) != digest:
            raise RuntimeError("production files changed since preparation")
    lock_path = ROOT / ".deploy-backups" / ".release.lock"
    with lock_path.open("w") as lock:
        os.chmod(lock_path, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        stopped = False
        changed = False
        try:
            command(["systemctl", "stop", "poi-hub-worker", "poi-hub-api"])
            stopped = True
            baseline = asyncio.run(snapshot(settings.database_url))
            if baseline["revision"] != BEFORE:
                raise RuntimeError("production migration version changed")
            command(
                ["pg_dump", "--format=custom", "--no-password"],
                env=database_env(url),
                output=BACKUP / "database-before-deploy.dump",
            )
            command(["pg_restore", "--list", str(BACKUP / "database-before-deploy.dump")])
            write_private(BACKUP / "publish-baseline.json", json.dumps(baseline).encode())
            changed = True
            for name in sorted(
                manifest["files"], key=lambda name: name == "frontend/dist/index.html"
            ):
                replace_file(STAGE / name, ROOT / name)
            # Keep every existing secret/value intact; only pin the new submission safety flag off.
            old_environment = (BACKUP / "environment-before").read_text()
            expression = r"(?m)^(?:export\s+)?WECHAT_APPLYMENT_SUBMIT_ENABLED\s*=.*$"
            if re.search(expression, old_environment):
                environment = re.sub(
                    expression, "WECHAT_APPLYMENT_SUBMIT_ENABLED=false", old_environment
                )
            else:
                environment = (
                    old_environment.rstrip("\n") + "\nWECHAT_APPLYMENT_SUBMIT_ENABLED=false\n"
                )
            temporary_env = BACKUP / "environment-next"
            write_private(temporary_env, environment.encode())
            replace_file(temporary_env, ROOT / ".env", mode=0o640)
            command(
                [
                    "runuser",
                    "-u",
                    "poi",
                    "--",
                    str(ROOT / ".venv/bin/python"),
                    "-m",
                    "alembic",
                    "upgrade",
                    "head",
                ]
            )
            check = command(
                [
                    str(ROOT / ".venv/bin/python"),
                    "-c",
                    "from poi_admin.core.config import get_settings; "
                    "s=get_settings(); assert not s.wechat_applyment_submit_enabled; "
                    "assert s.public_base_url=='https://poi.zzybyzz6369.my.id'; print('safe')",
                ],
                env={"PYTHONPATH": str(ROOT / "backend")},
            )
            if check.strip() != "safe":
                raise RuntimeError("new configuration probe failed")
            after = asyncio.run(snapshot(settings.database_url))
            if after["revision"] != AFTER or after["fingerprints"] != baseline["fingerprints"]:
                raise RuntimeError("protected records changed")
            command(["systemctl", "start", "poi-hub-api"])
            health()
            command(["systemctl", "start", "poi-hub-worker"])
            command(["systemctl", "is-active", "poi-hub-api", "poi-hub-worker", "nginx", "x-ui"])
            # Remove only the isolated rehearsal copy; the full production backups remain.
            if not CLONE.startswith("poi_verify_20261021_") or CLONE == url.database:
                raise RuntimeError("unsafe rehearsal database target")
            command(["runuser", "-u", "postgres", "--", "dropdb", CLONE])
            result = {
                "release": RELEASE,
                "revision": AFTER,
                "submit_enabled": False,
                "protected_records_unchanged": True,
                "counts": after["counts"],
                "backup": str(BACKUP),
                "services": "active",
                "rehearsal_copy_removed": True,
            }
            write_private(BACKUP / "deployed.json", json.dumps(result).encode())
            emit("deployed", **result)
        except Exception:
            if changed:
                command(["systemctl", "stop", "poi-hub-worker", "poi-hub-api"])
                # Application/config rollback only; never downgrade/drop production data tables.
                with tarfile.open(BACKUP / "source-before.tar.gz", "r:gz") as bundle:
                    for name, digest in originals.items():
                        target = scoped(ROOT / name, ROOT)
                        if digest is None:
                            if target.is_file():
                                target.unlink()
                            continue
                        member = bundle.getmember(name)
                        stream = bundle.extractfile(member)
                        if stream is None:
                            raise RuntimeError("rollback file missing")
                        restore_file = BACKUP / "restore-file"
                        write_private(restore_file, stream.read())
                        replace_file(restore_file, target)
                replace_file(BACKUP / "environment-before", ROOT / ".env", mode=0o640)
            if stopped:
                command(["systemctl", "start", "poi-hub-api", "poi-hub-worker"])
                health()
            emit("application_rolled_back", database_downgrade=False)
            raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["package", "prepare", "publish"])
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    if args.action == "package":
        package()
    elif args.action == "prepare":
        if not args.archive or not args.manifest:
            parser.error("archive and manifest required")
        prepare(args.archive, args.manifest)
    else:
        publish()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        emit("failed", error_type=type(error).__name__, message=str(error))
        raise SystemExit(1) from None
