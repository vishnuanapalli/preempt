"""The Azure provider, tested against recorded bytes and never the network.

That is not a preference. The live endpoint returned **HTTP 429** on a second request seconds
after the first, while it was being probed. A suite that calls it fails intermittently, on
someone else's machine, for reasons that have nothing to do with the code.

`fixtures/azure_retail_page1.json` and `page2.json` are real items from a real response to
`armRegionName eq 'eastus'`, trimmed to six: four spot meters (two Windows, two Linux) and
two on-demand ones, split across two pages so pagination is exercised rather than assumed.
Trimmed, not invented — a fixture that nobody ever received from the provider tests this
code against a fiction.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.providers.azure import ENDPOINT, fetch_spot_prices
from app.providers.base import (
    REGION_WIDE,
    ProviderUnavailable,
    UnexpectedResponse,
)

FIXTURES = Path(__file__).parent / "fixtures"
OBSERVED_AT = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())


def _client(pages: list[dict[str, Any]] | None = None, **kwargs: Any) -> httpx.Client:
    """A client serving recorded pages in order, or whatever `kwargs` dictates.

    `httpx.MockTransport` rather than monkeypatching: the provider's real request-building —
    params, URL handling, status codes — runs exactly as it would in production.
    """
    remaining = list(pages or [])

    def handler(request: httpx.Request) -> httpx.Response:
        if "status_code" in kwargs:
            return httpx.Response(kwargs["status_code"], text=kwargs.get("text", ""))
        if "raises" in kwargs:
            raise kwargs["raises"]
        if not remaining:
            raise AssertionError(f"unexpected extra request to {request.url}")
        return httpx.Response(200, json=remaining.pop(0))

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_it_follows_pagination_to_completion() -> None:
    """Two pages, six items. Stopping at page one would silently report a third fewer pools."""
    with _client([_fixture("azure_retail_page1.json"), _fixture("azure_retail_page2.json")]) as c:
        result = fetch_spot_prices(c, "eastus", OBSERVED_AT)

    assert result.pages == 2
    assert len(result) == 4, "four of the six recorded items are spot meters"
    assert result.skipped_not_spot == 2


def test_it_extracts_only_spot_meters() -> None:
    with _client([_fixture("azure_retail_page1.json"), _fixture("azure_retail_page2.json")]) as c:
        result = fetch_spot_prices(c, "eastus", OBSERVED_AT)

    types = {o.instance_type for o in result.observations}
    assert "Standard_DC8as_v5" not in types, "an on-demand meter was normalised as spot"
    assert "Standard_FX64mds_v2" not in types
    assert types == {
        "Standard_NC320ds_xl_RTXPRO6000BSE_v6",
        "Standard_GS2",
        "Standard_M32ts",
        "Standard_E48a_v4",
    }


def test_it_normalises_into_the_shared_shape() -> None:
    with _client([_fixture("azure_retail_page1.json"), _fixture("azure_retail_page2.json")]) as c:
        result = fetch_spot_prices(c, "eastus", OBSERVED_AT)

    by_type = {o.instance_type: o for o in result.observations}
    gs2 = by_type["Standard_GS2"]
    assert gs2.provider == "azure"
    assert gs2.region == "eastus"
    assert gs2.zone == REGION_WIDE, "the retail API prices a region, not a zone"
    assert gs2.os == "windows"
    assert gs2.source == "measured"
    assert gs2.observed_at == OBSERVED_AT
    # Exact, via str() — float(0.225456) carries binary rounding into money.
    assert gs2.price_usd_hour == Decimal("0.225456")
    assert by_type["Standard_M32ts"].os == "linux"


def test_the_price_keeps_full_precision() -> None:
    """A price that has been through a float is a price that will disagree with the invoice."""
    with _client([_fixture("azure_retail_page1.json"), _fixture("azure_retail_page2.json")]) as c:
        result = fetch_spot_prices(c, "eastus", OBSERVED_AT)
    prices = {o.price_usd_hour for o in result.observations}
    assert Decimal("6.2616") in prices
    assert all(isinstance(p, Decimal) for p in prices)


def test_non_hourly_meters_are_dropped_and_counted() -> None:
    """Counted, not silently discarded. A monthly figure beside an hourly one is worse than
    a missing row, and an uncounted drop reports a smaller world as complete."""
    page = _fixture("azure_retail_page1.json")
    page["Items"][0]["unitOfMeasure"] = "1 Month"
    page["NextPageLink"] = None
    with _client([page]) as c:
        result = fetch_spot_prices(c, "eastus", OBSERVED_AT)
    assert result.skipped_not_hourly == 1
    assert "Standard_NC320ds_xl_RTXPRO6000BSE_v6" not in {
        o.instance_type for o in result.observations
    }


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ({"Items": "not a list"}, "no 'Items' list"),
        ({"NextPageLink": 42}, "NextPageLink is not a string"),
    ],
)
def test_an_unexpected_body_raises_rather_than_returning_what_it_understood(
    mutation: dict[str, Any], reason: str
) -> None:
    page = _fixture("azure_retail_page1.json") | mutation
    with _client([page]) as c, pytest.raises(UnexpectedResponse, match=reason):
        fetch_spot_prices(c, "eastus", OBSERVED_AT)


@pytest.mark.parametrize("field", ["armSkuName", "productName", "armRegionName"])
def test_a_missing_required_field_raises(field: str) -> None:
    """Not defaulted. A blank instance type produces a pool with no name, which looks like
    data and is not."""
    page = _fixture("azure_retail_page1.json")
    page["NextPageLink"] = None
    del page["Items"][0][field]
    with _client([page]) as c, pytest.raises(UnexpectedResponse, match=field):
        fetch_spot_prices(c, "eastus", OBSERVED_AT)


def test_a_missing_price_raises_rather_than_becoming_zero() -> None:
    """Zero would read as a free machine and win every comparison."""
    page = _fixture("azure_retail_page1.json")
    page["NextPageLink"] = None
    del page["Items"][0]["unitPrice"]
    with _client([page]) as c, pytest.raises(UnexpectedResponse, match="unitPrice"):
        fetch_spot_prices(c, "eastus", OBSERVED_AT)


def test_rate_limiting_is_unavailable_not_a_contract_violation() -> None:
    """429 is what the live endpoint actually returns after two quick requests. It is
    retryable and says nothing about the provider's shape, so it must not be confused with
    a response this code cannot interpret."""
    with _client(status_code=429) as c, pytest.raises(ProviderUnavailable, match="429"):
        fetch_spot_prices(c, "eastus", OBSERVED_AT)


def test_a_transport_failure_is_unavailable() -> None:
    with (
        _client(raises=httpx.ConnectError("no route")) as c,
        pytest.raises(ProviderUnavailable, match="request failed"),
    ):
        fetch_spot_prices(c, "eastus", OBSERVED_AT)


def test_pagination_that_loops_is_refused_not_truncated() -> None:
    """A partial list is indistinguishable from a region with fewer pools, so the runaway
    guard raises instead of returning what it had."""
    looping = _fixture("azure_retail_page1.json") | {"NextPageLink": f"{ENDPOINT}?$skip=0"}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=looping)

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as c,
        pytest.raises(UnexpectedResponse, match="pagination exceeded"),
    ):
        fetch_spot_prices(c, "eastus", OBSERVED_AT)


def test_the_filter_is_sent_once_and_the_next_link_is_followed_verbatim() -> None:
    """`NextPageLink` already carries the filter. Re-sending it produced a working request
    against the live endpoint, so this is pinned by a test rather than by a comment."""
    seen: list[httpx.URL] = []
    pages = [_fixture("azure_retail_page1.json"), _fixture("azure_retail_page2.json")]

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        return httpx.Response(200, json=pages[len(seen) - 1])

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        fetch_spot_prices(c, "eastus", OBSERVED_AT)

    assert "%24filter=" in str(seen[0]) or "$filter=" in str(seen[0])
    assert "eastus" in str(seen[0])
    assert "recorded=page2" in str(seen[1]), "the second request must be the NextPageLink"
    assert "filter" not in str(seen[1]).lower(), "the filter must not be re-appended"
