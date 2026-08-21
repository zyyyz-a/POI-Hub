"""Import aliases for Alembic revisions used by migration tests and tooling."""

from importlib import import_module

_0002_identity = import_module(".0002_identity", __name__)
_0003_connections_operations = import_module(".0003_connections_operations", __name__)

__all__ = ["_0002_identity", "_0003_connections_operations"]
