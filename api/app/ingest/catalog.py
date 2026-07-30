"""Machine specs derived from Azure VM size names, or refused.

D-019: `instance_catalog` needs `vcpu` and `memory_mb`, and Azure's Retail Prices API returns
neither — it prices SKUs, it does not describe them. The specs live behind the authenticated
Resource SKUs API, which this project has no credentials for.

So they are **derived from the documented size naming convention**, in code, rather than typed
in as a table of numbers. That choice is about auditability: a derivation can be read, tested
and disagreed with, whereas a table of ~40 numbers asserted from memory is indistinguishable
from a table of invented ones. `spec_source` records which it is on every row.

The convention: `Standard_<family><vcpu>[modifiers]_v<version>` — the digits after the family
letter are the vCPU count, and each family has a documented memory-per-vCPU ratio. That is
enough for the general-purpose, compute- and memory-optimised families this project compares.

**Anything the convention does not cover is refused, not guessed.** GPU and high-memory
families (N-series, M-series) have per-size memory that no ratio predicts, so they return
`None` and the seed counts them as underivable. A wrong spec behind a real price is worse than
a missing pool: it makes a comparison confidently incorrect rather than visibly incomplete.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Documented GB of memory per vCPU, by family letter. These are the ratios Azure publishes
#: for its main VM families and they are the load-bearing constants in this module — a wrong
#: value here is wrong for every size in that family at once, which is exactly why they are
#: named here rather than buried in a lookup table of computed results.
#:
#:   B  burstable          — excluded: memory does not follow a ratio
#:   D  general purpose    4 GB/vCPU
#:   E  memory optimised   8 GB/vCPU
#:   F  compute optimised  2 GB/vCPU
#:   L  storage optimised  8 GB/vCPU
_MEMORY_GB_PER_VCPU = {"D": 4, "E": 8, "F": 2, "L": 8}

#: `Standard_` then a family letter, then the vCPU digits, then anything (modifiers such as
#: `s`, `d`, `a`, `as`, and an optional `_v5`). Anchored, so a name this does not fully
#: understand fails to match rather than matching partially.
_SIZE = re.compile(r"^Standard_(?P<family>[A-Z])(?P<vcpu>\d+)(?P<rest>[a-z_0-9]*)$")

#: Families whose memory is per-size rather than per-ratio. Listed so that refusing them is a
#: decision on the record rather than a gap in the regex.
UNDERIVABLE_FAMILIES = frozenset("BMNGH")


@dataclass(frozen=True)
class MachineSpec:
    vcpu: int
    memory_mb: int
    #: How these numbers came to exist. Never "measured" — nothing here fetched them.
    spec_source: str = "derived-from-name"


def derive_spec(instance_type: str) -> MachineSpec | None:
    """Specs for an Azure size name, or None when the convention cannot say.

    None is a real answer and the caller must handle it. Returning a plausible default would
    put fabricated hardware behind a real price, which is the failure D-019 exists to prevent.
    """
    match = _SIZE.match(instance_type)
    if match is None:
        return None

    family = match.group("family")
    if family in UNDERIVABLE_FAMILIES or family not in _MEMORY_GB_PER_VCPU:
        return None

    vcpu = int(match.group("vcpu"))
    if vcpu <= 0:
        return None

    return MachineSpec(vcpu=vcpu, memory_mb=vcpu * _MEMORY_GB_PER_VCPU[family] * 1024)


#: The curated set this project tracks. `01-DESIGN.md` caps tracked pools at 500 and says the
#: simulator follows "a curated subset rather than the full catalogue-by-zone cross product",
#: because the row budget is what makes 0.5 GB viable — not because the full set is unknowable.
#:
#: Chosen for comparison value: three families with genuinely different memory ratios, at
#: sizes small enough to be plausible spot targets and large enough to be interesting.
CURATED_AZURE_SIZES: tuple[str, ...] = (
    "Standard_D2s_v5",
    "Standard_D4s_v5",
    "Standard_D8s_v5",
    "Standard_D16s_v5",
    "Standard_E2s_v5",
    "Standard_E4s_v5",
    "Standard_E8s_v5",
    "Standard_E16s_v5",
    "Standard_F2s_v2",
    "Standard_F4s_v2",
    "Standard_F8s_v2",
    "Standard_F16s_v2",
)

#: The other two providers are simulated (D-001), and their sizes are named to make that
#: obvious in any output: nobody should mistake `sim.medium` for a real AWS instance type.
CURATED_SIMULATED_SIZES: dict[str, tuple[tuple[str, int, int], ...]] = {
    "aws": (
        ("sim.small", 2, 8 * 1024),
        ("sim.medium", 4, 16 * 1024),
        ("sim.large", 8, 32 * 1024),
        ("sim.xlarge", 16, 64 * 1024),
    ),
    "gcp": (
        ("sim.small", 2, 8 * 1024),
        ("sim.medium", 4, 16 * 1024),
        ("sim.large", 8, 32 * 1024),
        ("sim.xlarge", 16, 64 * 1024),
    ),
}
