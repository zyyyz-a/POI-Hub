def test_connections_operations_revision_follows_identity() -> None:
    from migrations.versions import _0003_connections_operations as revision

    assert revision.revision == "0003_connections_operations"
    assert revision.down_revision == "0002_identity"
