"""Application entrypoint.

Sprint 0 ships a walking skeleton: the smallest thing that can be deployed to the real
infrastructure and answer a request. Deploying now rather than at the end is deliberate —
every large unknown in this project is a free-tier behaviour that only appears in
production, and discovering one of those in the final sprint would invalidate decisions
everything else was built on.
"""

from __future__ import annotations

from fastapi import FastAPI

from app.api.v1 import health

app = FastAPI(
    title="Preempt",
    description=(
        "Compare spot pricing and interruption risk across AWS, Azure, and GCP. "
        "Azure prices are measured; AWS and GCP are simulated. Every price-bearing "
        "response states which."
    ),
    version="0.1.0",
)

app.include_router(health.router, prefix="/api/v1")
