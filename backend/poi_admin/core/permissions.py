"""Fixed least-privilege roles and backend authorization policies."""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    PLATFORM_ADMIN = "platform_admin"
    TENANT_ADMIN = "tenant_admin"
    OPERATOR = "operator"
    VERIFIER = "verifier"
    AUDITOR = "auditor"


class Permission(StrEnum):
    MANAGE_TENANTS = "manage_tenants"
    MANAGE_MEMBERS = "manage_members"
    VIEW_MEMBERS = "view_members"
    MANAGE_CONNECTIONS = "manage_connections"
    MANAGE_STORES = "manage_stores"
    VIEW_STORES = "view_stores"
    MANAGE_MAPPINGS = "manage_mappings"
    VIEW_MAPPINGS = "view_mappings"
    VIEW_PRODUCTS = "view_products"
    MANAGE_PRODUCTS = "manage_products"
    MANAGE_INVENTORY = "manage_inventory"
    VIEW_ORDERS = "view_orders"
    MANAGE_ORDERS = "manage_orders"
    CONSUME_VOUCHERS = "consume_vouchers"
    MANAGE_AFTER_SALES = "manage_after_sales"
    VIEW_ACCOUNTING = "view_accounting"
    VIEW_OPERATIONS = "view_operations"
    MANAGE_OPERATIONS = "manage_operations"
    VIEW_AUDIT = "view_audit"
    VIEW_DASHBOARD = "view_dashboard"


_TENANT_ADMIN_PERMISSIONS = frozenset(
    {
        Permission.MANAGE_MEMBERS,
        Permission.VIEW_MEMBERS,
        Permission.MANAGE_CONNECTIONS,
        Permission.MANAGE_STORES,
        Permission.VIEW_STORES,
        Permission.MANAGE_MAPPINGS,
        Permission.VIEW_MAPPINGS,
        Permission.VIEW_PRODUCTS,
        Permission.MANAGE_PRODUCTS,
        Permission.MANAGE_INVENTORY,
        Permission.VIEW_ORDERS,
        Permission.MANAGE_ORDERS,
        Permission.CONSUME_VOUCHERS,
        Permission.MANAGE_AFTER_SALES,
        Permission.VIEW_ACCOUNTING,
        Permission.VIEW_OPERATIONS,
        Permission.MANAGE_OPERATIONS,
        Permission.VIEW_AUDIT,
        Permission.VIEW_DASHBOARD,
    }
)

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.PLATFORM_ADMIN: frozenset(set(Permission)),
    Role.TENANT_ADMIN: _TENANT_ADMIN_PERMISSIONS,
    Role.OPERATOR: frozenset(
        {
            Permission.MANAGE_STORES,
            Permission.VIEW_STORES,
            Permission.MANAGE_MAPPINGS,
            Permission.VIEW_MAPPINGS,
            Permission.VIEW_PRODUCTS,
            Permission.MANAGE_PRODUCTS,
            Permission.MANAGE_INVENTORY,
            Permission.VIEW_ORDERS,
            Permission.MANAGE_ORDERS,
            Permission.VIEW_ACCOUNTING,
            Permission.VIEW_OPERATIONS,
            Permission.MANAGE_OPERATIONS,
            Permission.VIEW_DASHBOARD,
        }
    ),
    Role.VERIFIER: frozenset(
        {
            Permission.CONSUME_VOUCHERS,
            Permission.VIEW_ORDERS,
            Permission.VIEW_OPERATIONS,
        }
    ),
    Role.AUDITOR: frozenset(
        {
            Permission.VIEW_ACCOUNTING,
            Permission.VIEW_OPERATIONS,
            Permission.VIEW_AUDIT,
            Permission.VIEW_STORES,
            Permission.VIEW_MAPPINGS,
            Permission.VIEW_PRODUCTS,
            Permission.VIEW_ORDERS,
            Permission.VIEW_DASHBOARD,
        }
    ),
}


def coerce_role(role: Role | str) -> Role | None:
    """Convert persisted role values to a fixed role, rejecting unknown values."""

    try:
        return role if isinstance(role, Role) else Role(role)
    except ValueError:
        return None


def has_permission(role: Role | str | None, permission: Permission | str) -> bool:
    """Return whether a fixed role is allowed to perform a permission."""

    resolved_role = coerce_role(role) if role is not None else None
    if resolved_role is None:
        return False
    try:
        resolved_permission = (
            permission if isinstance(permission, Permission) else Permission(permission)
        )
    except ValueError:
        return False
    return resolved_permission in ROLE_PERMISSIONS[resolved_role]


__all__ = ["Permission", "ROLE_PERMISSIONS", "Role", "coerce_role", "has_permission"]
