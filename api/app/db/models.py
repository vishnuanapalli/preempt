"""The schema. Two relational tables and three hypertables, per `01-DESIGN.md`.

**The pool is the unit of everything** — one machine type, in one zone, for one operating
system. Risk is a property of a pool rather than of an individual machine, because
reclamations within a pool are driven by the same capacity pressure (D-004).

**Every fact table is keyed `(pool_id, observed_at)`.** Two reasons, and they agree:
TimescaleDB requires the partitioning column in any unique index, and per-pool history over
a time window is the primary read. It also means no separate index is needed for that
access pattern — an index that is an exact prefix of its own primary key is never-ship #20,
and the way that defect arrives is someone adding `(pool_id)` beside this key.

**Provenance is structural, not a footnote.** `source` is non-nullable on every fact row
and constrained to a known value, because a simulated price that loses its label is
indistinguishable from a measured one. `01-DESIGN.md` requires it on every response
carrying a price; a nullable column would make that impossible to honour later.

**Storage.** ~100 bytes per row against a 0.5 GB limit, with store-on-change writes and a
500-pool cap, targets ~2M rows worst case (`01-DESIGN.md`). TimescaleDB's default index on
the time column is left in place: disabling it would save space but changes the cost of
whole-fleet time scans, which is a trade to make with S-015's measured row counts rather
than guessed at now.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

#: Where a number came from. Checked in the database, not only in application code: a
#: constraint survives a bad migration and a direct psql session; a validator does not.
SOURCES = ("measured", "simulated")
_SOURCE_CHECK = "source IN ('measured', 'simulated')"

#: Providers this project compares. Azure is measured from its public API; the other two are
#: simulated and labelled as such everywhere they surface.
PROVIDERS = ("aws", "azure", "gcp")
_PROVIDER_CHECK = "provider IN ('aws', 'azure', 'gcp')"


class InstanceCatalog(Base):
    """A machine type as a provider offers it, independent of where it runs."""

    __tablename__ = "instance_catalog"
    __table_args__ = (
        UniqueConstraint("provider", "instance_type", name="uq_instance_catalog_provider_type"),
        CheckConstraint(_PROVIDER_CHECK, name="ck_instance_catalog_provider"),
        CheckConstraint("vcpu > 0", name="ck_instance_catalog_vcpu_positive"),
        CheckConstraint("memory_mb > 0", name="ck_instance_catalog_memory_positive"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    instance_type: Mapped[str] = mapped_column(String(64), nullable=False)
    vcpu: Mapped[int] = mapped_column(Integer, nullable=False)
    memory_mb: Mapped[int] = mapped_column(Integer, nullable=False)

    pools: Mapped[list[Pool]] = relationship(back_populates="catalog")


class Pool(Base):
    """One machine type, one zone, one OS. The unit risk is attached to."""

    __tablename__ = "pool"
    __table_args__ = (
        UniqueConstraint("catalog_id", "region", "zone", "os", name="uq_pool_identity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    catalog_id: Mapped[int] = mapped_column(
        ForeignKey("instance_catalog.id", ondelete="CASCADE"), nullable=False
    )
    region: Mapped[str] = mapped_column(String(32), nullable=False)
    zone: Mapped[str] = mapped_column(String(32), nullable=False)
    os: Mapped[str] = mapped_column(String(16), nullable=False)

    #: Updated on every observation, changed or not. This is what makes store-on-change
    #: safe: an unchanged price still proves the pool was seen, so a stale `last_seen`
    #: means ingestion stopped rather than that nothing moved.
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    catalog: Mapped[InstanceCatalog] = relationship(back_populates="pools")


class PriceMetric(Base):
    """Spot price for a pool at a moment. Written only when the price changed."""

    __tablename__ = "price_metric"
    __table_args__ = (
        CheckConstraint(_SOURCE_CHECK, name="ck_price_metric_source"),
        CheckConstraint("price_usd_hour >= 0", name="ck_price_metric_non_negative"),
    )

    pool_id: Mapped[int] = mapped_column(
        ForeignKey("pool.id", ondelete="CASCADE"), primary_key=True
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    price_usd_hour: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)


class CapacityMetric(Base):
    """A capacity-pressure signal for a pool. The feature risk scoring is built on."""

    __tablename__ = "capacity_metric"
    __table_args__ = (
        CheckConstraint(_SOURCE_CHECK, name="ck_capacity_metric_source"),
        CheckConstraint(
            "capacity_score >= 0 AND capacity_score <= 1", name="ck_capacity_metric_range"
        ),
    )

    pool_id: Mapped[int] = mapped_column(
        ForeignKey("pool.id", ondelete="CASCADE"), primary_key=True
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    #: 0 = no pressure, 1 = maximum. A unit interval rather than a provider's own scale, so
    #: three providers' signals are comparable; the constraint is what keeps it that way.
    capacity_score: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)


class InterruptionEvent(Base):
    """A reclamation observed in a pool. The label prediction is trained against."""

    __tablename__ = "interruption_event"
    __table_args__ = (
        CheckConstraint(_SOURCE_CHECK, name="ck_interruption_event_source"),
        CheckConstraint("reclaimed_count > 0", name="ck_interruption_event_count_positive"),
    )

    pool_id: Mapped[int] = mapped_column(
        ForeignKey("pool.id", ondelete="CASCADE"), primary_key=True
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    reclaimed_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    source: Mapped[str] = mapped_column(String(16), nullable=False)


#: The three fact tables, in dependency order. `alembic/versions` converts each to a
#: hypertable and drops them in reverse; keeping the list here means the migration and the
#: models cannot disagree about which tables are partitioned.
HYPERTABLES: tuple[str, ...] = ("price_metric", "capacity_metric", "interruption_event")
