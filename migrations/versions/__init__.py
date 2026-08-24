"""Import aliases for Alembic revisions used by migration tests and tooling."""

from importlib import import_module

_0002_identity = import_module(".0002_identity", __name__)
_0003_connections_operations = import_module(".0003_connections_operations", __name__)
_0006_local_life_orders = import_module(".0006_local_life_orders", __name__)
_0007_webhooks = import_module(".0007_webhooks", __name__)
_0008_audit = import_module(".0008_audit", __name__)
_0009_batch_delivery = import_module(".0009_batch_delivery", __name__)
_0010_wechat_contracts = import_module(".0010_wechat_contracts", __name__)

__all__ = [
    "_0002_identity",
    "_0003_connections_operations",
    "_0006_local_life_orders",
    "_0007_webhooks",
    "_0008_audit",
    "_0009_batch_delivery",
    "_0010_wechat_contracts",
]
