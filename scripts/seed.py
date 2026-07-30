#!/usr/bin/env python3
"""Seed the instance catalog. Idempotent, and the recovery path when the database is lost.

S-005, deferred out of Sprint 0 because Sprint 0 had no tables to seed. It became
load-bearing in S-013: the writer refuses to invent `vcpu`/`memory_mb` for an instance type it
has never seen (D-019), so until this has run a production tick counts nearly every
observation as `unknown_instance_type`.

**Idempotent by construction, not by checking first.** `ON CONFLICT DO NOTHING` on the natural
key means running this twice leaves exactly the same rows, with no read-then-write race
between the check and the insert.

**Specs are derived, and every row says so.** Azure's price feed carries no hardware
description, so `app/ingest/catalog.py` derives vCPU and memory from the documented size
naming convention and refuses anything the convention cannot express. Refused sizes are
reported, never silently dropped.

    cd api && uv run python ../scripts/seed.py            # against PREEMPT_DATABASE_URL
    cd api && uv run python ../scripts/seed.py --test-db  # against PREEMPT_TEST_DATABASE_URL
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.ingest.catalog import (
    CURATED_AZURE_SIZES,
    CURATED_SIMULATED_SIZES,
    derive_spec,
)

_INSERT = text("""
    INSERT INTO instance_catalog (provider, instance_type, vcpu, memory_mb)
    VALUES (:provider, :instance_type, :vcpu, :memory_mb)
    ON CONFLICT (provider, instance_type) DO NOTHING
    RETURNING id
""")


async def seed(url: str) -> tuple[int, int, int]:
    """Returns (inserted, already_present, underivable). Counts come from the database."""
    rows: list[dict[str, object]] = []
    underivable = 0

    for size in CURATED_AZURE_SIZES:
        spec = derive_spec(size)
        if spec is None:
            # Reported rather than skipped in silence: a size the convention cannot express is
            # a gap in coverage, and a seed that quietly plants fewer rows than it lists is how
            # "the provider offers less" becomes the wrong conclusion.
            print(f"  underivable, refused: azure {size}", file=sys.stderr)
            underivable += 1
            continue
        rows.append(
            {
                "provider": "azure",
                "instance_type": size,
                "vcpu": spec.vcpu,
                "memory_mb": spec.memory_mb,
            }
        )

    for provider, sizes in CURATED_SIMULATED_SIZES.items():
        for name, vcpu, memory_mb in sizes:
            rows.append(
                {
                    "provider": provider,
                    "instance_type": name,
                    "vcpu": vcpu,
                    "memory_mb": memory_mb,
                }
            )

    engine = create_async_engine(url, connect_args={"statement_cache_size": 0})
    inserted = 0
    try:
        async with engine.begin() as conn:
            for row in rows:
                if (await conn.execute(_INSERT, row)).scalar_one_or_none() is not None:
                    inserted += 1
    finally:
        await engine.dispose()

    return inserted, len(rows) - inserted, underivable


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--test-db",
        action="store_true",
        help="seed PREEMPT_TEST_DATABASE_URL instead of the application database",
    )
    args = parser.parse_args()

    url = settings.test_database_url if args.test_db else settings.database_url
    if not url:
        which = "PREEMPT_TEST_DATABASE_URL" if args.test_db else "PREEMPT_DATABASE_URL"
        print(f"{which} is not set; nothing to seed.", file=sys.stderr)
        return 2

    inserted, present, underivable = asyncio.run(seed(url))
    print(
        f"catalog: {inserted} inserted, {present} already present, {underivable} underivable "
        f"(specs derived from the size naming convention, not fetched)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
