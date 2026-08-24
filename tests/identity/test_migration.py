from __future__ import annotations


def test_identity_revision_follows_foundation_revision() -> None:
    from migrations.versions import _0002_identity as identity_revision

    assert identity_revision.revision == "0002_identity"
    assert identity_revision.down_revision == "0001_foundation"
