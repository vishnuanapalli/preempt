"""Spec derivation, and the seed's idempotence.

The derivation exists because Azure's price feed carries no hardware description and typing
~40 numbers in from memory would be indistinguishable from inventing them (D-019). A
derivation can be read and disagreed with; that is the whole argument for it, so the ratios it
depends on are asserted here against sizes whose specs are widely published.

`refuses` is the important half. A wrong spec behind a real price makes a comparison
confidently incorrect, which is worse than a pool that is visibly missing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.ingest.catalog import (
    CURATED_AZURE_SIZES,
    CURATED_SIMULATED_SIZES,
    derive_spec,
)

# `scripts/` is not a package and is not on the path. Inserted here rather than inside the
# test, because touching pathlib in an async body trips ASYNC240 — and the lint is right that
# a blocking filesystem call in a coroutine is worth flagging even when it is harmless.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from seed import seed


@pytest.mark.parametrize(
    ("size", "vcpu", "memory_gb"),
    [
        # D is general purpose at 4 GB/vCPU, E memory-optimised at 8, F compute-optimised at 2.
        ("Standard_D2s_v5", 2, 8),
        ("Standard_D16s_v5", 16, 64),
        ("Standard_E4s_v5", 4, 32),
        ("Standard_E16s_v5", 16, 128),
        ("Standard_F2s_v2", 2, 4),
        ("Standard_F16s_v2", 16, 32),
        ("Standard_L8s_v3", 8, 64),
    ],
)
def test_specs_follow_the_documented_family_ratios(size: str, vcpu: int, memory_gb: int) -> None:
    spec = derive_spec(size)
    assert spec is not None, f"{size} should be derivable"
    assert spec.vcpu == vcpu
    assert spec.memory_mb == memory_gb * 1024
    assert spec.spec_source == "derived-from-name", "a derived spec must never claim to be measured"


@pytest.mark.parametrize(
    "size",
    [
        "Standard_NC320ds_xl_RTXPRO6000BSE_v6",  # GPU: memory is per-size, no ratio predicts it
        "Standard_M32ts",  # high memory: same
        "Standard_B2s",  # burstable: memory does not follow a ratio
        "Standard_GS2",  # G family: not in the ratio table
        "not_a_size",
        "Standard_D0s_v5",  # zero vCPU is not a machine
        "",
    ],
)
def test_it_refuses_what_the_convention_cannot_express(size: str) -> None:
    """None is a real answer. A plausible default here is fabricated hardware behind a real
    price — the failure D-019 exists to prevent."""
    assert derive_spec(size) is None


def test_every_curated_azure_size_is_derivable() -> None:
    """The curated list and the derivation must agree, or the seed plants fewer rows than it
    lists and the shortfall reads as the provider offering less."""
    underivable = [s for s in CURATED_AZURE_SIZES if derive_spec(s) is None]
    assert not underivable, f"curated sizes the convention cannot express: {underivable}"


def test_simulated_sizes_are_named_so_nobody_mistakes_them_for_real_ones() -> None:
    """`01-DESIGN.md` requires simulated data to be labelled everywhere it surfaces. A name
    like `m5.large` in an AWS row would defeat that no matter what `source` said."""
    for provider, sizes in CURATED_SIMULATED_SIZES.items():
        for name, vcpu, memory_mb in sizes:
            assert name.startswith("sim."), f"{provider} size {name!r} reads as a real type"
            assert vcpu > 0
            assert memory_mb > 0


@pytest.mark.integration
async def test_seeding_twice_leaves_the_same_rows() -> None:
    """S-005's idempotence criterion, against the real database.

    By construction rather than by checking first: `ON CONFLICT DO NOTHING` on the natural key
    has no window between a read and a write for a second run to slip through.
    """
    url = settings.test_database_url
    if not url:
        pytest.skip("PREEMPT_TEST_DATABASE_URL unset, so the seed's behaviour is UNPROVEN here")

    engine = create_async_engine(url, connect_args={"statement_cache_size": 0})
    try:
        async with engine.connect():
            pass
    except Exception as exc:
        await engine.dispose()
        pytest.skip(f"test database unreachable ({type(exc).__name__}), seed UNPROVEN here")

    try:
        async with engine.begin() as conn:
            await conn.execute(text("TRUNCATE price_metric, pool, instance_catalog CASCADE"))

        first_inserted, first_present, _ = await seed(url)
        second_inserted, second_present, _ = await seed(url)

        async with engine.connect() as conn:
            rows = (await conn.execute(text("SELECT count(*) FROM instance_catalog"))).scalar_one()

        assert first_inserted > 0, "the first run inserted nothing"
        assert first_present == 0, "an empty catalog reported rows already present"
        assert second_inserted == 0, "the second run inserted rows again — not idempotent"
        assert second_present == first_inserted
        assert rows == first_inserted, "running twice changed the row count"
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("TRUNCATE price_metric, pool, instance_catalog CASCADE"))
        await engine.dispose()
