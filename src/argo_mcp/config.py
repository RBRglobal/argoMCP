"""Configuration for the Argo MCP server."""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

# Argovis API
ARGOVIS_BASE_URL: str = os.getenv(
    "ARGOVIS_BASE_URL", "https://argovis-api.colorado.edu"
)
ARGOVIS_API_KEY: str | None = os.getenv("ARGOVIS_API_KEY")

# Euro-Argo Fleet Monitoring API
EUROARGO_BASE_URL: str = "https://fleetmonitoring.euro-argo.eu"

# HTTP client defaults
REQUEST_TIMEOUT: float = 30.0
MAX_RETRIES: int = 3
RETRY_BACKOFF_FACTOR: float = 1.0

# Default query limits
DEFAULT_MAX_RESULTS: int = 50
MAX_RESULTS_LIMIT: int = 1000

# Argo citation (must be included with data responses)
ARGO_CITATION: str = (
    "These data were collected and made freely available by the "
    "international Argo project and the national programs that contribute to it."
)
ARGO_DOI: str = "https://doi.org/10.17882/42182"

# Core and BGC parameter names (Argo Reference Table R03)
CORE_PARAMETERS: list[str] = ["TEMP", "PSAL", "PRES"]
BGC_PARAMETERS: list[str] = [
    "DOXY",
    "CHLA",
    "BBP700",
    "PH_IN_SITU_TOTAL",
    "NITRATE",
    "DOWN_IRRADIANCE",
    "CDOM",
]
ALL_PARAMETERS: list[str] = CORE_PARAMETERS + BGC_PARAMETERS
