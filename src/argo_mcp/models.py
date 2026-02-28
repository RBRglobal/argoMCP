"""Pydantic models for structured Argo MCP responses."""

from __future__ import annotations

from pydantic import BaseModel, Field

from argo_mcp.config import ARGO_CITATION, ARGO_DOI


# ---------------------------------------------------------------------------
# Mixins / base
# ---------------------------------------------------------------------------

class ArgoResponse(BaseModel):
    """Base response that carries the mandatory Argo citation."""

    citation: str = Field(default=ARGO_CITATION)
    doi: str = Field(default=ARGO_DOI)


# ---------------------------------------------------------------------------
# Tier 1 — Discovery & Search
# ---------------------------------------------------------------------------

class ProfileMeta(BaseModel):
    """Lightweight profile metadata returned by search."""

    wmo_number: int
    cycle: int
    longitude: float
    latitude: float
    date: str
    data_mode: str | None = None


class SearchProfilesResponse(ArgoResponse):
    """Response for search_profiles."""

    profiles: list[ProfileMeta]
    total_count: int


class FloatMetadata(ArgoResponse):
    """Platform metadata for a single float."""

    wmo_number: int
    dac: str | None = None
    float_model: str | None = None
    deployment_date: str | None = None
    deployment_longitude: float | None = None
    deployment_latitude: float | None = None
    transmission_system: str | None = None
    sensors: list[str] = Field(default_factory=list)
    cycles: int | None = None
    most_recent_date: str | None = None
    most_recent_longitude: float | None = None
    most_recent_latitude: float | None = None


class FloatSummary(BaseModel):
    """Concise float entry for region listing."""

    wmo_number: int
    longitude: float
    latitude: float
    most_recent_date: str | None = None
    dac: str | None = None


class ListFloatsResponse(ArgoResponse):
    """Response for list_floats_in_region."""

    floats: list[FloatSummary]
    total_count: int


class TrajectoryPoint(BaseModel):
    """A single point in a float trajectory."""

    longitude: float
    latitude: float
    date: str
    cycle: int | None = None


class TrajectoryResponse(ArgoResponse):
    """Response for get_float_trajectory."""

    wmo_number: int
    points: list[TrajectoryPoint]


# ---------------------------------------------------------------------------
# Tier 2 — Data Retrieval
# ---------------------------------------------------------------------------

class Measurement(BaseModel):
    """A single depth-level measurement."""

    pressure: float | None = None
    temperature: float | None = None
    salinity: float | None = None
    depth: float | None = None


class ProfileData(ArgoResponse):
    """Full profile data."""

    wmo_number: int
    cycle: int
    longitude: float
    latitude: float
    date: str
    data_mode: str | None = None
    parameters: list[str]
    levels: list[dict]
    qc_filter_applied: bool = True


class RegionProfilesResponse(ArgoResponse):
    """Response for get_profiles_in_region."""

    profiles: list[ProfileData]
    total_count: int


class BGCMeasurement(BaseModel):
    """A single BGC depth-level measurement."""

    pressure: float | None = None
    values: dict[str, float | None] = Field(default_factory=dict)
    qc_flags: dict[str, int | None] = Field(default_factory=dict)


class BGCProfileData(ArgoResponse):
    """BGC profile data."""

    wmo_number: int
    cycle: int
    longitude: float
    latitude: float
    date: str
    variables: list[str]
    levels: list[BGCMeasurement]
    qc_filter_applied: bool = True


# ---------------------------------------------------------------------------
# Tier 3 — Analysis
# ---------------------------------------------------------------------------

class MLDResult(ArgoResponse):
    """Result of mixed layer depth computation."""

    wmo_number: int
    cycle: int
    mld_meters: float | None = None
    method: str
    reference_pressure: float | None = None
    reference_temperature: float | None = None
    reference_density: float | None = None
    threshold_used: float | None = None
    error: str | None = None


class ProfileComparison(ArgoResponse):
    """Side-by-side comparison of two cycles."""

    wmo_number: int
    cycle_a: int
    cycle_b: int
    date_a: str | None = None
    date_b: str | None = None
    mean_temp_a: float | None = None
    mean_temp_b: float | None = None
    mean_sal_a: float | None = None
    mean_sal_b: float | None = None
    delta_mean_temp: float | None = None
    delta_mean_sal: float | None = None
    depth_range_a: list[float] = Field(default_factory=list)
    depth_range_b: list[float] = Field(default_factory=list)
    levels_a: int = 0
    levels_b: int = 0


class RegionSummary(ArgoResponse):
    """Aggregate stats for a region."""

    profile_count: int
    float_count: int
    data_mode_distribution: dict[str, int] = Field(default_factory=dict)
    mean_temperature_by_depth: dict[str, float] = Field(default_factory=dict)
    mean_salinity_by_depth: dict[str, float] = Field(default_factory=dict)
    date_range: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Tier 4 — QC-Aware
# ---------------------------------------------------------------------------

class CycleQC(BaseModel):
    """QC info for one cycle."""

    cycle: int
    data_mode: str | None = None
    qc_flag_distribution: dict[str, int] = Field(default_factory=dict)


class QCSummary(ArgoResponse):
    """QC summary for a float."""

    wmo_number: int
    total_cycles: int
    data_mode_distribution: dict[str, int] = Field(default_factory=dict)
    cycles: list[CycleQC] = Field(default_factory=list)


class AdjustedProfileData(ArgoResponse):
    """Delayed-mode adjusted profile."""

    wmo_number: int
    cycle: int
    longitude: float
    latitude: float
    date: str
    parameters: list[str]
    levels: list[dict]
    adjusted: bool = True
