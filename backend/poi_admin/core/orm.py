"""Shared SQLAlchemy declarative base for application models."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class shared by every bounded context."""


__all__ = ["Base"]
