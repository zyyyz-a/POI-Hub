"""Read-only HTTPS smoke checks against the deployed SaaS; never authenticates."""

import argparse
import hashlib
import json
from pathlib import Path

import httpx

BASE = "https://poi.zzybyzz6369.my.id"
ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / ".data/releases/release-20261021-merchant-applyments.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--check-photo-limit", action="store_true")
    args = parser.parse_args()
    expected = {
        "/api/v1/health/ready": 200,
        "/login": 200,
        "/merchant-applyments": 200,
        "/api/v1/merchant-applyments/capabilities": 401,
        "/api/v1/me": 401,
        "/api/v1/public/platform/stores/disifengshang": 200,
    }
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    report: dict[str, object] = {"base": BASE, "tls_verified": True}
    endpoints = []
    assets = []
    with httpx.Client(timeout=20, follow_redirects=True) as client:
        for path, status in expected.items():
            response = client.get(BASE + path)
            endpoints.append({"path": path, "status": response.status_code})
            if response.status_code != status:
                raise RuntimeError(f"Unexpected HTTPS response for {path}: {response.status_code}")
            if path == "/login":
                digest = hashlib.sha256(response.content).hexdigest()
                if digest != manifest["files"]["frontend/dist/index.html"]:
                    raise RuntimeError("Public frontend index is not the built release")
            if path.endswith("/disifengshang"):
                store = response.json()
                report["store_tradable"] = store.get("tradable")
                if store.get("tradable") is True:
                    raise RuntimeError("Pilot real store unexpectedly became tradable")
        for name, digest in manifest["files"].items():
            if not name.startswith("frontend/dist/assets/"):
                continue
            path = name.removeprefix("frontend/dist")
            response = client.get(BASE + path)
            matches = (
                response.status_code == 200
                and hashlib.sha256(response.content).hexdigest() == digest
            )
            assets.append(
                {"path": path, "status": response.status_code, "checksum_matches": matches}
            )
            if not matches:
                raise RuntimeError("Public frontend asset mismatch")
        if args.check_photo_limit:
            checks = []
            for size in [3 * 1024 * 1024, 5 * 1024 * 1024]:
                # No auth cookie, fake application ID, synthetic bytes:
                # no business write is possible.
                response = client.post(
                    BASE
                    + "/api/v1/merchant-applyments/upload-size-probe/attachments/license?version=1",
                    headers={"Content-Type": "image/png"},
                    content=b"\0" * size,
                    timeout=60,
                )
                checks.append({"bytes": size, "status": response.status_code})
                if response.status_code != 401:
                    raise RuntimeError("Upload blocked before normal authentication check")
            report["photo_size_checks"] = checks
    report.update(endpoints=endpoints, assets=assets, result="passed")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
