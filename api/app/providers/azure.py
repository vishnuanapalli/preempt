"""Azure spot prices from the public Retail Prices API. The one measured provider.

No credentials: the endpoint is public and unauthenticated, which is why Azure is the
provider this project measures rather than simulates (D-001).

**Everything below was observed against the live endpoint before it was written**, and two
observations shaped it:

- **`$top` is ignored.** A request with `$top=5` returned 1000 items. Page size is the
  server's to choose, so `NextPageLink` is the only page control and the loop must follow it
  rather than assume a size.
- **It rate-limits, hard.** A second request seconds after the first returned **HTTP 429**.
  That is why `fetch_spot_prices` takes an injected client, why 429 maps to
  `ProviderUnavailable` (retryable) rather than `UnexpectedResponse`, and why the tests read
  recorded payloads and never touch the network — a test suite that hits this endpoint will
  fail for reasons unrelated to the code, on someone else's machine, intermittently.

**What is filtered where.** `serviceName`, `priceType` and `armRegionName` are filtered
server-side; all three were confirmed working in a live response. Spot is filtered
client-side on `skuName`, because OData `contains()` could not be verified — the request
testing it is the one that hit 429 — and building on an unverified filter is how a provider
silently returns nothing. Moving it server-side would cut the payload roughly threefold and
is worth doing once it can be confirmed.

**Two honest approximations, both visible in the data they produce:**

- **No availability zone.** The retail API prices a region, not a zone, so every pool is
  `REGION_WIDE`. Azure spot capacity genuinely varies by zone; this data cannot see that.
- **Operating system is inferred from a display string.** `productName` containing "Windows"
  means Windows, and anything else is treated as Linux. RHEL and SUSE appear as their own
  products and will be labelled `linux`, which is wrong in a way worth knowing about before
  anyone reads an OS breakdown as authoritative.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.providers.base import (
    REGION_WIDE,
    FetchResult,
    PriceObservation,
    ProviderUnavailable,
    UnexpectedResponse,
)

PROVIDER = "azure"
ENDPOINT = "https://prices.azure.com/api/retail/prices"

#: Confirmed working against the live endpoint. `contains(skuName, 'Spot')` is deliberately
#: absent — see the module docstring.
_FILTER = (
    "serviceName eq 'Virtual Machines' and priceType eq 'Consumption' "
    "and armRegionName eq '{region}'"
)

#: The only unit this project can compare. Azure also prices per month and per 10 hours;
#: mixing units silently would put a monthly figure next to an hourly one.
_HOURLY = "1 Hour"

#: A page limit, so a broken `NextPageLink` cannot loop forever. Observed page size is 1000
#: and a single region returns roughly one page of spot meters, so this is far above any real
#: response — it is a runaway guard, not a cap on data, and hitting it is an error rather
#: than a truncated result.
_MAX_PAGES = 50


def _decimal(value: Any, field: str, item: dict[str, Any]) -> Decimal:
    """Parse a price, or refuse. Never a default — a missing price is not a free machine."""
    if value is None:
        raise UnexpectedResponse(PROVIDER, f"{field} is missing from item {item.get('meterId')!r}")
    try:
        # Via str, because float(6.2616) carries binary rounding into a Decimal that will be
        # stored as money.
        return Decimal(str(value))
    except (InvalidOperation, TypeError) as exc:
        raise UnexpectedResponse(
            PROVIDER, f"{field} is not a number: {value!r} in item {item.get('meterId')!r}"
        ) from exc


def _require(item: dict[str, Any], field: str) -> str:
    value = item.get(field)
    if not isinstance(value, str) or not value:
        raise UnexpectedResponse(
            PROVIDER, f"{field} is missing or not a string in item {item.get('meterId')!r}"
        )
    return value


def _operating_system(product_name: str) -> str:
    """Inferred from a display string; see the module docstring for why that is a compromise."""
    return "windows" if "windows" in product_name.lower() else "linux"


def _is_spot(item: dict[str, Any]) -> bool:
    return "spot" in item.get("skuName", "").lower()


def _observation(item: dict[str, Any], observed_at: datetime) -> PriceObservation:
    return PriceObservation(
        provider=PROVIDER,
        instance_type=_require(item, "armSkuName"),
        region=_require(item, "armRegionName"),
        zone=REGION_WIDE,
        os=_operating_system(_require(item, "productName")),
        price_usd_hour=_decimal(item.get("unitPrice"), "unitPrice", item),
        source="measured",
        observed_at=observed_at,
    )


def _page(client: httpx.Client, url: str, params: dict[str, str] | None) -> dict[str, Any]:
    try:
        response = client.get(url, params=params)
    except httpx.HTTPError as exc:
        raise ProviderUnavailable(PROVIDER, f"request failed: {exc}") from exc

    if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
        raise ProviderUnavailable(PROVIDER, "rate limited (HTTP 429)")
    if response.status_code >= httpx.codes.BAD_REQUEST:
        raise ProviderUnavailable(PROVIDER, f"HTTP {response.status_code}")

    try:
        body = response.json()
    except ValueError as exc:
        raise UnexpectedResponse(PROVIDER, "response body is not JSON") from exc
    if not isinstance(body, dict) or not isinstance(body.get("Items"), list):
        raise UnexpectedResponse(PROVIDER, "response has no 'Items' list")
    return body


def fetch_spot_prices(
    client: httpx.Client, region: str, observed_at: datetime | None = None
) -> FetchResult:
    """Every spot price for one region, or an exception. Never a partial list.

    The client is injected rather than created here so tests can serve recorded payloads —
    the endpoint rate-limits, so a suite that calls it is a suite that fails for unrelated
    reasons.
    """
    stamp = observed_at or datetime.now(UTC)
    observations: list[PriceObservation] = []
    not_hourly = not_spot = 0
    url: str | None = ENDPOINT
    params: dict[str, str] | None = {"$filter": _FILTER.format(region=region)}
    pages = 0

    while url:
        pages += 1
        if pages > _MAX_PAGES:
            # Refuse rather than return what was collected: a truncated result is
            # indistinguishable from a region that genuinely has fewer pools.
            raise UnexpectedResponse(
                PROVIDER, f"pagination exceeded {_MAX_PAGES} pages; NextPageLink may be looping"
            )
        body = _page(client, url, params)

        for item in body["Items"]:
            if not isinstance(item, dict):
                raise UnexpectedResponse(PROVIDER, f"item is not an object: {item!r}")
            if not _is_spot(item):
                not_spot += 1
                continue
            if item.get("unitOfMeasure") != _HOURLY:
                not_hourly += 1
                continue
            observations.append(_observation(item, stamp))

        # NextPageLink already carries the filter, so params must not be sent again.
        next_link = body.get("NextPageLink")
        if next_link is not None and not isinstance(next_link, str):
            raise UnexpectedResponse(PROVIDER, f"NextPageLink is not a string: {next_link!r}")
        url, params = next_link, None

    return FetchResult(
        observations=tuple(observations),
        pages=pages,
        skipped_not_hourly=not_hourly,
        skipped_not_spot=not_spot,
    )
