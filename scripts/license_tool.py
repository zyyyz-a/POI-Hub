"""Generate vendor keys and issue offline appliance license files."""

from __future__ import annotations

import argparse
import base64
import json
import secrets
from datetime import UTC, datetime
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from poi_admin.core.licensing import LicenseClaims, canonical_claims


def _write_new(path: Path, value: str) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def generate_keys(private_path: Path, public_path: Path) -> None:
    private_key = Ed25519PrivateKey.generate()
    private_bytes = private_key.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    public_bytes = private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    _write_new(private_path, base64.b64encode(private_bytes).decode("ascii"))
    _write_new(public_path, base64.b64encode(public_bytes).decode("ascii"))


def issue_license(args: argparse.Namespace) -> None:
    private_bytes = base64.b64decode(args.private_key.read_text(encoding="utf-8").strip())
    private_key = Ed25519PrivateKey.from_private_bytes(private_bytes)
    claims = LicenseClaims(
        license_id=args.license_id or f"lic-{secrets.token_hex(8)}",
        customer_id=args.customer_id,
        customer_name=args.customer_name,
        installation_id=args.installation_id,
        issued_at=datetime.now(UTC),
        expires_at=datetime.fromisoformat(args.expires_at.replace("Z", "+00:00")),
        max_stores=args.max_stores,
        features=args.features,
    )
    signature = private_key.sign(canonical_claims(claims))
    envelope = {
        "claims": claims.model_dump(mode="json"),
        "signature": base64.b64encode(signature).decode("ascii"),
    }
    _write_new(
        args.output,
        json.dumps(envelope, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    key_parser = subparsers.add_parser("generate-keys")
    key_parser.add_argument("--private-key", type=Path, required=True)
    key_parser.add_argument("--public-key", type=Path, required=True)

    issue_parser = subparsers.add_parser("issue")
    issue_parser.add_argument("--private-key", type=Path, required=True)
    issue_parser.add_argument("--output", type=Path, required=True)
    issue_parser.add_argument("--license-id")
    issue_parser.add_argument("--customer-id", required=True)
    issue_parser.add_argument("--customer-name", required=True)
    issue_parser.add_argument("--installation-id", required=True)
    issue_parser.add_argument("--expires-at", required=True)
    issue_parser.add_argument("--max-stores", type=int, required=True)
    issue_parser.add_argument("--features", nargs="*", default=[])

    args = parser.parse_args()
    if args.command == "generate-keys":
        generate_keys(args.private_key, args.public_key)
    else:
        issue_license(args)


if __name__ == "__main__":
    main()
