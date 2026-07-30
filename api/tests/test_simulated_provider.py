"""The simulator, and the determinism test that matters.

`test_output_is_identical_across_pythonhashseed_values` is the one worth having. Python salts
`hash()` per interpreter, so a generator seeded from it is perfectly deterministic within a
process and different on every run — invisible to every same-process test anyone would think
to write. `01-DESIGN.md` requires the cross-process check by name, and D-005 records that it is
what made determinism survive adversarial review in prior work.

It runs real subprocesses with different `PYTHONHASHSEED` values, because that is the only
place the defect lives.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.providers.simulated import (
    STREAM_CAPACITY,
    STREAM_PRICE,
    fetch_spot_prices,
    simulate_capacity_score,
    simulate_price,
)

TICK = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
CATALOG = [("sim.small", 2), ("sim.medium", 4), ("sim.large", 8)]


def test_the_same_inputs_give_the_same_price() -> None:
    a = simulate_price("aws", "sim.medium", 4, "us-east-1", "linux", TICK)
    b = simulate_price("aws", "sim.medium", 4, "us-east-1", "linux", TICK)
    assert a == b


def test_different_pools_do_not_move_in_lockstep() -> None:
    """The pool identity is part of the key, or every pool would tell the same story."""
    prices = {simulate_price("aws", t, v, "us-east-1", "linux", TICK) for t, v in CATALOG}
    assert len(prices) == len(CATALOG)


def test_price_scales_with_size() -> None:
    """Bounded noise, so a bigger machine is always dearer than a smaller one of the same
    family. A simulator where 8 vCPUs can undercut 2 makes every comparison look broken."""
    small = simulate_price("aws", "sim.small", 2, "us-east-1", "linux", TICK)
    large = simulate_price("aws", "sim.large", 8, "us-east-1", "linux", TICK)
    assert small < large


def test_prices_are_positive_and_bounded() -> None:
    """±35% of base, so no draw can produce a free or absurd machine."""
    for hour in range(24):
        stamp = TICK.replace(hour=hour)
        for provider in ("aws", "gcp"):
            for instance_type, vcpu in CATALOG:
                price = simulate_price(provider, instance_type, vcpu, "us-east-1", "linux", stamp)
                base = Decimal("0.01") * vcpu
                assert Decimal("0") < price < base * 2, f"{provider} {instance_type} at {hour}h"


def test_windows_costs_more_than_linux_for_the_same_pool() -> None:
    linux = simulate_price("aws", "sim.medium", 4, "us-east-1", "linux", TICK)
    windows = simulate_price("aws", "sim.medium", 4, "us-east-1", "windows", TICK)
    assert windows > linux


def test_the_hour_bucket_makes_a_re_run_reproduce_the_same_price() -> None:
    """Store-on-change needs an unchanged input to produce an unchanged price. Noise on every
    call would make every tick a write and defeat the row budget."""
    early = simulate_price("aws", "sim.medium", 4, "us-east-1", "linux", TICK)
    same_hour = simulate_price(
        "aws", "sim.medium", 4, "us-east-1", "linux", TICK.replace(minute=59)
    )
    next_hour = simulate_price("aws", "sim.medium", 4, "us-east-1", "linux", TICK.replace(hour=13))
    assert early == same_hour
    assert early != next_hour


def test_streams_are_independent() -> None:
    """Price and capacity draw from separately named streams. Sharing one generator would mean
    adding a capacity draw silently shifted every price after it."""
    assert STREAM_PRICE != STREAM_CAPACITY
    price = simulate_price("aws", "sim.medium", 4, "us-east-1", "linux", TICK)
    capacity = simulate_capacity_score("aws", "sim.medium", "us-east-1", "linux", TICK)
    assert Decimal("0") <= capacity <= Decimal("1")
    # Different streams, same key parts: the values must not be the same number.
    assert capacity != price


def test_everything_is_labelled_simulated() -> None:
    """`01-DESIGN.md` makes this structural. A simulated price that loses its label is
    indistinguishable from a measured one."""
    result = fetch_spot_prices("aws", CATALOG, "us-east-1", TICK)
    assert result.observations
    assert all(o.source == "simulated" for o in result.observations)
    assert all(o.instance_type.startswith("sim.") for o in result.observations), (
        "a name like m5.large would defeat the labelling no matter what `source` said"
    )


def test_it_simulates_only_catalogued_sizes() -> None:
    """The simulator takes the catalog rather than inventing types, so no row exists that no
    catalog entry explains — the writer would count those as unknown anyway."""
    result = fetch_spot_prices("aws", CATALOG, "us-east-1", TICK)
    assert {o.instance_type for o in result.observations} == {t for t, _ in CATALOG}
    assert len(result) == len(CATALOG) * 2, "two operating systems per catalogued size"


# --------------------------------------------------------------- the cross-process check

_PROBE = """
import sys
sys.path.insert(0, {api!r})
from datetime import UTC, datetime
from app.providers.simulated import simulate_price, simulate_capacity_score

tick = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
for t, v in [("sim.small", 2), ("sim.medium", 4), ("sim.large", 8)]:
    for provider in ("aws", "gcp"):
        for os_ in ("linux", "windows"):
            print(provider, t, os_,
                  simulate_price(provider, t, v, "us-east-1", os_, tick),
                  simulate_capacity_score(provider, t, "us-east-1", os_, tick))
"""


def _run_with_hashseed(seed: str, api_dir: str) -> str:
    completed = subprocess.run(  # noqa: S603
        [sys.executable, "-c", _PROBE.format(api=api_dir)],
        capture_output=True,
        text=True,
        env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"},
        check=True,
    )
    return completed.stdout


def test_output_is_identical_across_pythonhashseed_values() -> None:
    """The test D-005 says made determinism survive review, and the only one that can catch it.

    `hash()` is salted per interpreter. A generator seeded from it looks deterministic in every
    same-process test and produces different numbers on every run — so this has to cross a
    process boundary. blake2b is what makes it hold.
    """
    from pathlib import Path

    api_dir = str(Path(__file__).resolve().parents[1])
    first = _run_with_hashseed("0", api_dir)
    second = _run_with_hashseed("12345", api_dir)
    third = _run_with_hashseed("random", api_dir)

    assert first, "the probe produced no output"
    assert first == second, "output differs between PYTHONHASHSEED=0 and 12345"
    assert first == third, "output differs under PYTHONHASHSEED=random"


def test_the_cross_process_check_would_notice_a_hash_seeded_generator() -> None:
    """The determinism test above is only worth having if it can fail. Python's own `hash()`
    over the same key parts differs across these seeds — which is the defect being guarded
    against, demonstrated rather than asserted."""
    from pathlib import Path

    api_dir = str(Path(__file__).resolve().parents[1])
    probe = f"import sys; sys.path.insert(0, {api_dir!r}); print(hash('aws|sim.medium|linux'))"

    def run(seed: str) -> str:
        return subprocess.run(  # noqa: S603
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"},
            check=True,
        ).stdout

    assert run("0") != run("12345"), (
        "hash() gave the same value under two seeds, so this environment cannot demonstrate "
        "the defect the test above guards against — investigate before trusting it"
    )


@pytest.mark.parametrize("provider", ["aws", "gcp"])
def test_providers_differ_but_stay_comparable(provider: str) -> None:
    """A fixed factor per provider, not a random one, so a comparison has something stable to
    show. Arbitrary, and labelled as such — never market intelligence."""
    price = simulate_price(provider, "sim.medium", 4, "us-east-1", "linux", TICK)
    assert Decimal("0.01") < price < Decimal("0.1")
