"""Declarative base.

Every model imports from here, and Alembic reads `Base.metadata` to detect changes. A
model that is never imported is invisible to autogenerate, so new model modules must be
imported in `app/db/models.py` even when nothing references them directly.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
