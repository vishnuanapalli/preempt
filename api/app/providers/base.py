"""The shape every provider normalises into, and the errors they may raise.

One shape for three providers is what makes the comparison possible at all: Azure is
measured from its public API, AWS and GCP are simulated, and a response that mixes them
must be able to say which is which per row. `source` is therefore not optional and not
inferred later — it is set where the number is produced.

**A provider returns everything or raises.** Never a partial list. A truncated page set
looks exactly like a provider that genuinely has fewer pools, and the difference only
surfaces later as a comparison quietly missing a region. `01-DESIGN.md`'s error contract
and never-ship #5 both point the same way: report counts derived from what happened, and
make dropped rows visible rather than absent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

#: A pool that is region-scoped rather than zone-scoped. Azure's retail price API reports
#: prices per region with no availability zone, so a literal is used rather than an empty
#: string: a reader looking at a row should be able to tell this is not a zone name that
#: went missing. The schema requires `zone` to be non-null.
REGION_WIDE = "region-wide"


class ProviderError(Exception):
    """Base for every provider failure. Carries the provider so logs are attributable."""

    def __init__(self, provider: str, message: str) -> None:
        super().__init__(f"{provider}: {message}")
        self.provider = provider


class ProviderUnavailable(ProviderError):
    """The provider could not be reached, or refused the request.

    Distinct from `UnexpectedResponse` on purpose: this one is worth retrying and says
    nothing about the provider's contract. Rate limiting lands here — the Azure retail API
    returns 429 after very few requests in quick succession, observed while probing it.
    """


class UnexpectedResponse(ProviderError):
    """The provider answered, but not in a shape this code can honestly interpret.

    Raised rather than skipped. A missing `unitPrice` could be treated as zero and a missing
    `armSkuName` as blank, and both would produce rows that look like data — a free machine,
    or a pool with no name. Refusing is the only reading that cannot mislead.
    """


@dataclass(frozen=True)
class PriceObservation:
    """One pool's spot price at one moment, normalised across providers."""

    provider: str
    instance_type: str
    region: str
    zone: str
    os: str
    price_usd_hour: Decimal
    #: "measured" or "simulated". Structural, per `01-DESIGN.md` — a simulated price that
    #: loses its label is indistinguishable from a real one.
    source: str
    observed_at: datetime


@dataclass(frozen=True)
class FetchResult:
    """What a fetch produced, including what it deliberately left out.

    The counts exist so nothing is dropped silently. A provider that quietly discards rows
    it does not understand reports a smaller world and calls it complete.
    """

    observations: tuple[PriceObservation, ...]
    pages: int
    #: Priced per month, per 10 hours, or otherwise not per hour. Mixing units is worse than
    #: dropping them, so they are dropped — and counted.
    skipped_not_hourly: int
    #: On-demand and reserved meters. Not an error: the endpoint serves every price type.
    skipped_not_spot: int

    def __len__(self) -> int:
        return len(self.observations)
