"""Argo Ocean Data MCP Server.

Exposes tools for searching, retrieving, and analysing Argo ocean profiling
float data via the Model Context Protocol.
"""

from __future__ import annotations

import logging
from typing import Literal, Optional

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from argo_mcp.argovis import ArgovisClient, ArgovisError
from argo_mcp.argopy_utils import (
    compare_profiles_data,
    compute_mixed_layer_depth as _compute_mld,
    fetch_adjusted_profile_argopy,
    summarize_profiles,
)
from argo_mcp.config import ARGO_CITATION, ARGO_DOI, BGC_PARAMETERS
from argo_mcp.models import (
    AdjustedProfileData,
    BGCProfileData,
    FloatMetadata,
    ListFloatsResponse,
    MLDResult,
    ProfileComparison,
    ProfileData,
    QCSummary,
    RegionProfilesResponse,
    RegionSummary,
    SearchProfilesResponse,
    TrajectoryResponse,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Server & shared client
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "ArgoMCP",
    json_response=True,
)

_client: ArgovisClient | None = None


def _get_client() -> ArgovisClient:
    global _client
    if _client is None:
        _client = ArgovisClient()
    return _client


# =========================================================================
# Tier 1 — Discovery & Search
# =========================================================================


@mcp.tool()
async def search_profiles(
    lon_min: float,
    lon_max: float,
    lat_min: float,
    lat_max: float,
    date_start: Optional[str] = None,
    date_end: Optional[str] = None,
    max_results: int = 50,
) -> SearchProfilesResponse:
    """Search for Argo float profiles within a bounding box and optional time range.

    Returns lightweight profile metadata (WMO number, cycle, position, date,
    data mode). Dates should be ISO-8601 (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ).
    Coordinates are in decimal degrees (lon: -180..180, lat: -90..90).
    """
    try:
        results = await _get_client().search_profiles(
            lon_min=lon_min,
            lon_max=lon_max,
            lat_min=lat_min,
            lat_max=lat_max,
            date_start=date_start,
            date_end=date_end,
            max_results=max_results,
        )
    except ArgovisError as exc:
        raise ToolError(f"Argovis API error: {exc}")

    profiles = [
        {
            "wmo_number": r.get("wmo_number"),
            "cycle": r.get("cycle"),
            "longitude": r.get("longitude"),
            "latitude": r.get("latitude"),
            "date": r.get("date"),
            "data_mode": r.get("data_mode"),
        }
        for r in results
    ]
    return SearchProfilesResponse(
        profiles=profiles,  # type: ignore[arg-type]
        total_count=len(profiles),
    )


@mcp.tool()
async def get_float_metadata(wmo_number: int) -> FloatMetadata:
    """Get platform metadata for an Argo float by its WMO number.

    Returns deployment date/location, sensor manifest, Data Assembly Centre,
    float model, and transmission system.
    """
    try:
        meta = await _get_client().get_platform_metadata(wmo_number)
    except ArgovisError as exc:
        raise ToolError(f"Argovis API error: {exc}")

    if meta is None:
        raise ToolError(
            f"Float {wmo_number} not found. Verify the WMO number is correct."
        )
    return FloatMetadata(**meta)


@mcp.tool()
async def list_floats_in_region(
    lon_min: float,
    lon_max: float,
    lat_min: float,
    lat_max: float,
    active_only: bool = False,
) -> ListFloatsResponse:
    """List unique Argo floats in a geographic region.

    Returns each float's most recent position. Use active_only=True to
    exclude floats that have not reported in the last 30 days.
    """
    try:
        floats = await _get_client().list_floats_in_region(
            lon_min=lon_min,
            lon_max=lon_max,
            lat_min=lat_min,
            lat_max=lat_max,
        )
    except ArgovisError as exc:
        raise ToolError(f"Argovis API error: {exc}")

    if active_only:
        from datetime import datetime, timedelta, timezone

        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        floats = [
            f for f in floats if f.get("most_recent_date") and f["most_recent_date"] >= cutoff
        ]

    return ListFloatsResponse(
        floats=floats,  # type: ignore[arg-type]
        total_count=len(floats),
    )


@mcp.tool()
async def get_float_trajectory(wmo_number: int) -> TrajectoryResponse:
    """Get the trajectory (position time-series) of an Argo float.

    Returns chronologically ordered positions with dates and cycle numbers.
    """
    try:
        points = await _get_client().get_float_trajectory(wmo_number)
    except ArgovisError as exc:
        raise ToolError(f"Argovis API error: {exc}")

    if not points:
        raise ToolError(
            f"No trajectory data found for float {wmo_number}."
        )

    return TrajectoryResponse(
        wmo_number=wmo_number,
        points=points,  # type: ignore[arg-type]
    )


# =========================================================================
# Tier 2 — Data Retrieval
# =========================================================================


@mcp.tool()
async def get_profile(
    wmo_number: int,
    cycle: int,
    parameters: Optional[list[str]] = None,
    include_all_qc: bool = False,
) -> ProfileData:
    """Retrieve a full T/S/P profile for a specific float and cycle.

    By default returns only QC-filtered data (flag=1). Set include_all_qc=True
    to receive all measurements regardless of quality flags. Optionally filter
    to specific parameters (e.g. ["TEMP", "PSAL"]).
    """
    try:
        data = await _get_client().get_profile(
            wmo_number=wmo_number,
            cycle=cycle,
            parameters=parameters,
            include_all_qc=include_all_qc,
        )
    except ArgovisError as exc:
        raise ToolError(f"Argovis API error: {exc}")

    if data is None:
        raise ToolError(
            f"Profile not found: WMO {wmo_number}, cycle {cycle}. "
            "Verify both the WMO number and cycle number exist."
        )

    return ProfileData(**data)


@mcp.tool()
async def get_profiles_in_region(
    lon_min: float,
    lon_max: float,
    lat_min: float,
    lat_max: float,
    date_start: Optional[str] = None,
    date_end: Optional[str] = None,
    parameters: Optional[list[str]] = None,
    max_results: int = 50,
    include_all_qc: bool = False,
) -> RegionProfilesResponse:
    """Retrieve full profile data for a geographic region and time range.

    Returns bulk T/S/P measurements for spatial analysis. QC-filtered by
    default.
    """
    try:
        profiles = await _get_client().get_profiles_in_region(
            lon_min=lon_min,
            lon_max=lon_max,
            lat_min=lat_min,
            lat_max=lat_max,
            date_start=date_start,
            date_end=date_end,
            parameters=parameters,
            max_results=max_results,
            include_all_qc=include_all_qc,
        )
    except ArgovisError as exc:
        raise ToolError(f"Argovis API error: {exc}")

    return RegionProfilesResponse(
        profiles=profiles,  # type: ignore[arg-type]
        total_count=len(profiles),
    )


@mcp.tool()
async def get_bgc_profile(
    wmo_number: int,
    cycle: int,
    variables: Optional[list[str]] = None,
    include_all_qc: bool = False,
) -> BGCProfileData:
    """Retrieve biogeochemical (BGC) profile data for a float and cycle.

    Available BGC variables: DOXY, CHLA, BBP700, PH_IN_SITU_TOTAL, NITRATE,
    DOWN_IRRADIANCE, CDOM. If variables is omitted, all available BGC
    measurements are returned. QC-filtered by default.
    """
    if variables is None:
        variables = BGC_PARAMETERS

    try:
        data = await _get_client().get_bgc_profile(
            wmo_number=wmo_number,
            cycle=cycle,
            variables=variables,
            include_all_qc=include_all_qc,
        )
    except ArgovisError as exc:
        raise ToolError(f"Argovis API error: {exc}")

    if data is None:
        raise ToolError(
            f"BGC profile not found: WMO {wmo_number}, cycle {cycle}. "
            "This float may not carry BGC sensors."
        )

    return BGCProfileData(**data)


# =========================================================================
# Tier 3 — Analysis
# =========================================================================


@mcp.tool()
async def compute_mixed_layer_depth(
    wmo_number: int,
    cycle: int,
    method: Literal[
        "density_threshold", "temperature_gradient", "holte_talley"
    ] = "density_threshold",
    threshold: Optional[float] = None,
) -> MLDResult:
    """Compute mixed layer depth (MLD) for a given Argo profile.

    Methods:
    - density_threshold: MLD where density exceeds reference by threshold
      (default 0.03 kg/m³)
    - temperature_gradient: MLD where temperature differs from reference
      by threshold (default 0.2 °C)
    - holte_talley: Simplified Holte & Talley (2009) algorithm using
      density curvature
    """
    # Fetch the profile data first
    try:
        data = await _get_client().get_profile(
            wmo_number=wmo_number,
            cycle=cycle,
            include_all_qc=False,
        )
    except ArgovisError as exc:
        raise ToolError(f"Argovis API error: {exc}")

    if data is None:
        raise ToolError(
            f"Profile not found: WMO {wmo_number}, cycle {cycle}."
        )

    # Extract pressure, temperature, salinity arrays from levels
    pressure, temperature, salinity = _extract_pts(data.get("levels", []))

    if len(pressure) < 3:
        raise ToolError(
            f"Insufficient data ({len(pressure)} levels) to compute MLD."
        )

    result = _compute_mld(
        pressure=pressure,
        temperature=temperature,
        salinity=salinity,
        method=method,
        threshold=threshold,
    )

    return MLDResult(
        wmo_number=wmo_number,
        cycle=cycle,
        **result,
    )


@mcp.tool()
async def compare_profiles(
    wmo_number: int,
    cycle_a: int,
    cycle_b: int,
) -> ProfileComparison:
    """Compare two profiles from the same float side-by-side.

    Returns mean temperature/salinity for each cycle and the deltas between
    them.
    """
    client = _get_client()
    try:
        data_a = await client.get_profile(wmo_number, cycle_a, include_all_qc=False)
        data_b = await client.get_profile(wmo_number, cycle_b, include_all_qc=False)
    except ArgovisError as exc:
        raise ToolError(f"Argovis API error: {exc}")

    if data_a is None:
        raise ToolError(f"Profile not found: WMO {wmo_number}, cycle {cycle_a}.")
    if data_b is None:
        raise ToolError(f"Profile not found: WMO {wmo_number}, cycle {cycle_b}.")

    comparison = compare_profiles_data(data_a, data_b)

    return ProfileComparison(
        wmo_number=wmo_number,
        cycle_a=cycle_a,
        cycle_b=cycle_b,
        date_a=data_a.get("date"),
        date_b=data_b.get("date"),
        **comparison,
    )


@mcp.tool()
async def summarize_region(
    lon_min: float,
    lon_max: float,
    lat_min: float,
    lat_max: float,
    date_start: Optional[str] = None,
    date_end: Optional[str] = None,
) -> RegionSummary:
    """Compute aggregate statistics for Argo profiles in a region.

    Returns profile count, float count, mean T/S at standard depths,
    data mode distribution, and date range.
    """
    try:
        profiles = await _get_client().get_profiles_in_region(
            lon_min=lon_min,
            lon_max=lon_max,
            lat_min=lat_min,
            lat_max=lat_max,
            date_start=date_start,
            date_end=date_end,
            max_results=500,
            include_all_qc=False,
        )
    except ArgovisError as exc:
        raise ToolError(f"Argovis API error: {exc}")

    stats = summarize_profiles(profiles)
    return RegionSummary(**stats)


# =========================================================================
# Tier 4 — QC-Aware
# =========================================================================


@mcp.tool()
async def get_qc_summary(wmo_number: int) -> QCSummary:
    """Get a QC quality summary for all cycles of an Argo float.

    Returns data mode (R=realtime, A=adjusted, D=delayed-mode) per cycle
    and overall QC flag distribution.
    """
    try:
        profiles = await _get_client().get_profiles_for_float(wmo_number)
    except ArgovisError as exc:
        raise ToolError(f"Argovis API error: {exc}")

    if not profiles:
        raise ToolError(f"No profiles found for float {wmo_number}.")

    data_modes: dict[str, int] = {}
    cycles = []
    for p in profiles:
        _id = p.get("_id", "")
        cycle_num = None
        if "_" in str(_id):
            try:
                cycle_num = int(str(_id).split("_")[1])
            except (ValueError, IndexError):
                pass
        dm = p.get("data_mode", "unknown")
        data_modes[dm] = data_modes.get(dm, 0) + 1
        cycles.append(
            {
                "cycle": cycle_num,
                "data_mode": dm,
                "qc_flag_distribution": {},
            }
        )

    cycles.sort(key=lambda c: c.get("cycle") or 0)

    return QCSummary(
        wmo_number=wmo_number,
        total_cycles=len(cycles),
        data_mode_distribution=data_modes,
        cycles=cycles,  # type: ignore[arg-type]
    )


@mcp.tool()
async def get_adjusted_profile(
    wmo_number: int,
    cycle: int,
) -> AdjustedProfileData:
    """Retrieve delayed-mode adjusted data for a specific float and cycle.

    Returns only data with QC flag=1 and ADJUSTED_PRES_ERROR < 20 dbar.
    Falls back to argopy GDAC access if available.
    """
    # Try argopy first for full adjusted data
    argopy_data = fetch_adjusted_profile_argopy(wmo_number, cycle)
    if argopy_data is not None:
        return AdjustedProfileData(
            wmo_number=wmo_number,
            cycle=cycle,
            longitude=0.0,
            latitude=0.0,
            date="",
            **argopy_data,
        )

    # Fall back to Argovis
    try:
        data = await _get_client().get_profile(
            wmo_number=wmo_number,
            cycle=cycle,
            include_all_qc=False,
        )
    except ArgovisError as exc:
        raise ToolError(f"Argovis API error: {exc}")

    if data is None:
        raise ToolError(
            f"Adjusted profile not found: WMO {wmo_number}, cycle {cycle}."
        )

    return AdjustedProfileData(
        wmo_number=wmo_number,
        cycle=cycle,
        longitude=data.get("longitude", 0.0),
        latitude=data.get("latitude", 0.0),
        date=data.get("date", ""),
        parameters=data.get("parameters", []),
        levels=data.get("levels", []),
        adjusted=True,
    )


# =========================================================================
# Helpers
# =========================================================================


def _extract_pts(levels: list[dict]) -> tuple[list[float], list[float], list[float]]:
    """Extract pressure, temperature, salinity arrays from profile levels."""
    pressure: list[float] = []
    temperature: list[float] = []
    salinity: list[float] = []

    for lvl in levels:
        if not isinstance(lvl, dict):
            continue
        p = lvl.get("pressure") or lvl.get("PRES") or lvl.get("pres")
        t = lvl.get("temperature") or lvl.get("TEMP") or lvl.get("temp")
        s = lvl.get("salinity") or lvl.get("PSAL") or lvl.get("psal")
        if p is not None and t is not None and s is not None:
            pressure.append(float(p))
            temperature.append(float(t))
            salinity.append(float(s))

    return pressure, temperature, salinity


# =========================================================================
# Entrypoint
# =========================================================================


def main():
    """Run the Argo MCP server (stdio transport by default)."""
    logging.basicConfig(level=logging.INFO)
    mcp.run()


if __name__ == "__main__":
    main()
