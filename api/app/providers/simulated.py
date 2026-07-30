"""Simulated spot prices for AWS and GCP. Deterministic, and labelled as simulated everywhere.

D-001: only Azure publishes spot prices without credentials, so the other two providers are
simulated. `01-DESIGN.md` makes the labelling structural rather than a footnote — `source` is
`"simulated"` on every row, and the instance types are named `sim.*` so a name alone gives it
away even if a caller drops the field.

**Determinism is the property that matters, and it has two halves.**

Same seed, same output — that part is easy. The harder half is *across processes*: Python
salts `hash()` per interpreter, so any generator seeded from `hash(something)` produces
different numbers on every run while looking perfectly deterministic within one. `01-DESIGN.md`
requires identical output across two `PYTHONHASHSEED` values and a test asserts it, because
this is the failure that survives every same-process test anyone would think to write.

So keys are hashed with **blake2b**, not `hash()`. Stable across processes, versions and
platforms.

**Named streams per concern.** Price, capacity and interruption each draw from their own
generator, seeded from the pool identity *and* the stream name. One shared generator would
couple them: adding a capacity draw would silently change every price that followed it, and a
regression test written before the change would fail for reasons unrelated to prices. That is
the same "carried forward from prior work" note in D-005 — it is what made determinism survive
adversarial review there.

**These are not forecasts.** The walk has no economics in it: prices drift around a
size-proportional base with bounded noise. It exists so the comparison, the storage path and
the risk model have three providers to work with, and nothing here should ever be read as a
claim about what AWS or GCP actually charge.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from decimal import Decimal

from app.providers.base import REGION_WIDE, FetchResult, PriceObservation

#: Streams are named, so a new draw cannot shift an existing one.
STREAM_PRICE = "price"
STREAM_CAPACITY = "capacity"
STREAM_INTERRUPTION = "interruption"

#: USD per vCPU-hour before noise. Chosen to sit in the same order of magnitude as the
#: measured Azure spot prices this is compared against — around $0.01/vCPU-hour — so a chart
#: with all three providers on it is legible rather than dominated by one.
_BASE_USD_PER_VCPU_HOUR = Decimal("0.0100")

#: Providers diverge by a fixed factor rather than randomly, so a comparison has something
#: stable to show. Simulated, and therefore arbitrary — stated so nobody reads it as market
#: intelligence.
_PROVIDER_FACTOR = {"aws": Decimal("1.00"), "gcp": Decimal("0.92")}

#: Bounded so a simulated price can never be negative or absurd: ±35% of base.
_SWING = Decimal("0.35")


def _unit_interval(*parts: str) -> Decimal:
    """A stable pseudo-random value in [0, 1) from the given key parts.

    blake2b rather than `hash()`: Python's `hash()` is salted per interpreter, so a generator
    seeded from it is deterministic within a process and different across processes. That is
    exactly the failure `01-DESIGN.md` requires a test for, and it is invisible to any
    single-process test.
    """
    digest = hashlib.blake2b("\x00".join(parts).encode(), digest_size=8).digest()
    # 2**64 as the denominator, so the result is in [0, 1) with uniform spacing.
    return Decimal(int.from_bytes(digest, "big")) / Decimal(2**64)


def simulate_price(
    provider: str, instance_type: str, vcpu: int, region: str, os: str, observed_at: datetime
) -> Decimal:
    """One pool's simulated price at one moment. Same inputs, same output, always."""
    factor = _PROVIDER_FACTOR.get(provider, Decimal("1.00"))
    base = _BASE_USD_PER_VCPU_HOUR * vcpu * factor
    if os == "windows":
        # A licence premium, so the two OS variants of a pool are not identical. Arbitrary,
        # like everything else here.
        base *= Decimal("1.6")

    # The timestamp is part of the key, so the walk moves; the pool identity is too, so two
    # pools never move in lockstep. Bucketed to the hour, so re-running a tick within the
    # same hour reproduces the same price and store-on-change is exercised rather than
    # defeated by noise.
    bucket = observed_at.strftime("%Y-%m-%dT%H")
    draw = _unit_interval(STREAM_PRICE, provider, instance_type, region, os, bucket)
    swing = (draw * 2 - 1) * _SWING  # [-0.35, 0.35)
    return (base * (1 + swing)).quantize(Decimal("0.000001"))


def simulate_capacity_score(
    provider: str, instance_type: str, region: str, os: str, observed_at: datetime
) -> Decimal:
    """Capacity pressure in [0, 1]. Its own stream, so adding it changed no price."""
    bucket = observed_at.strftime("%Y-%m-%dT%H")
    draw = _unit_interval(STREAM_CAPACITY, provider, instance_type, region, os, bucket)
    return draw.quantize(Decimal("0.001"))


def fetch_spot_prices(
    provider: str,
    catalog: list[tuple[str, int]],
    region: str,
    observed_at: datetime,
    operating_systems: tuple[str, ...] = ("linux", "windows"),
) -> FetchResult:
    """Simulated observations for every catalogued size, in the shared shape.

    Signature deliberately unlike the Azure provider's: this one takes the catalog rather than
    discovering it, because a simulator inventing instance types would put names in the data
    that no catalog row explains. `catalog` is `(instance_type, vcpu)` pairs.
    """
    observations = [
        PriceObservation(
            provider=provider,
            instance_type=instance_type,
            region=region,
            zone=REGION_WIDE,
            os=os,
            price_usd_hour=simulate_price(provider, instance_type, vcpu, region, os, observed_at),
            source="simulated",
            observed_at=observed_at,
        )
        for instance_type, vcpu in catalog
        for os in operating_systems
    ]
    return FetchResult(
        observations=tuple(observations),
        pages=1,
        skipped_not_hourly=0,
        skipped_not_spot=0,
    )
