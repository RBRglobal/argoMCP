"""Async client for the Argovis REST API (v2).

Reference: https://argovis.colorado.edu/apiintro
Base URL:  https://argovis-api.colorado.edu

Response data structure:
  - ``data_info[0]`` = list of variable names (e.g. ["pressure","temperature","salinity"])
  - ``data_info[1]`` = list of metadata keys (e.g. ["units","long_name"])
  - ``data_info[2]`` = per-variable metadata arrays
  - ``data`` = 2-D array where each sub-array holds one *variable's* values
    across depth levels.  Use ``zip(*data)`` to transpose into per-level tuples.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from argo_mcp.config import (
    ARGOVIS_API_KEY,
    ARGOVIS_BASE_URL,
    MAX_RETRIES,
    REQUEST_TIMEOUT,
    RETRY_BACKOFF_FACTOR,
)

logger = logging.getLogger(__name__)


class ArgovisError(Exception):
    """Raised when an Argovis API call fails."""


class ArgovisClient:
    """Async wrapper around the Argovis v2 API."""

    def __init__(
        self,
        base_url: str = ARGOVIS_BASE_URL,
        api_key: str | None = ARGOVIS_API_KEY,
        timeout: float = REQUEST_TIMEOUT,
    ) -> None:
        headers: dict[str, str] = {"Accept": "application/json"}
        if api_key:
            headers["x-argokey"] = api_key
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers=headers,
            timeout=timeout,
        )

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET with retry + backoff."""
        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                resp = await self._client.get(path, params=params)
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                return resp.json()
            except (httpx.HTTPStatusError, httpx.TransportError) as exc:
                last_exc = exc
                if attempt < MAX_RETRIES:
                    wait = RETRY_BACKOFF_FACTOR * (2**attempt)
                    logger.warning(
                        "Argovis request %s failed (attempt %d/%d), retrying in %.1fs: %s",
                        path,
                        attempt + 1,
                        MAX_RETRIES + 1,
                        wait,
                        exc,
                    )
                    await asyncio.sleep(wait)
        raise ArgovisError(f"Argovis request {path} failed after retries: {last_exc}")

    @staticmethod
    def _fmt_date(dt: str) -> str:
        """Ensure ISO-8601 with trailing Z for Argovis."""
        if "T" not in dt:
            dt = dt + "T00:00:00Z"
        if not dt.endswith("Z"):
            dt = dt + "Z"
        return dt

    @staticmethod
    def _bbox_to_polygon(
        lon_min: float, lon_max: float, lat_min: float, lat_max: float
    ) -> str:
        """Convert bounding box to Argovis polygon parameter.

        Argovis expects a stringified list of ``[lon, lat]`` pairs forming
        a closed ring.
        """
        coords = [
            [lon_min, lat_min],
            [lon_min, lat_max],
            [lon_max, lat_max],
            [lon_max, lat_min],
            [lon_min, lat_min],
        ]
        return str(coords).replace(" ", "")

    # ------------------------------------------------------------------
    # Data inflation helper
    # ------------------------------------------------------------------

    @staticmethod
    def _inflate(item: dict) -> tuple[list[str], list[dict]]:
        """Inflate the Argovis compact data representation.

        Returns ``(variable_names, levels)`` where *levels* is a list of
        dicts mapping variable name → value for each depth level.
        """
        data_info = item.get("data_info", [])
        data = item.get("data", [])

        # data_info[0] holds variable names
        if data_info and len(data_info) > 0:
            var_names: list[str] = data_info[0]
        else:
            var_names = []

        if not data or not var_names:
            return var_names, []

        # data is transposed: each sub-array is one variable across levels.
        # zip(*data) gives per-level tuples.
        levels: list[dict] = []
        for level_vals in zip(*data):
            level = {var_names[i]: v for i, v in enumerate(level_vals)}
            levels.append(level)
        return var_names, levels

    # ------------------------------------------------------------------
    # Tier 1 — Discovery & Search
    # ------------------------------------------------------------------

    async def search_profiles(
        self,
        lon_min: float,
        lon_max: float,
        lat_min: float,
        lat_max: float,
        date_start: str | None = None,
        date_end: str | None = None,
        max_results: int = 50,
    ) -> list[dict]:
        """Search for Argo profiles within a bounding box and time window."""
        params: dict[str, Any] = {
            "polygon": self._bbox_to_polygon(lon_min, lon_max, lat_min, lat_max),
            "compression": "minimal",
        }
        if date_start:
            params["startDate"] = self._fmt_date(date_start)
        if date_end:
            params["endDate"] = self._fmt_date(date_end)

        data = await self._get("/argo", params=params)
        if not data:
            return []

        results: list[dict] = []
        for item in data[:max_results]:
            geoloc = item.get("geolocation", {})
            coords = geoloc.get("coordinates", [None, None])
            results.append(
                {
                    "wmo_number": self._extract_wmo(item),
                    "cycle": self._extract_cycle(item),
                    "longitude": coords[0] if len(coords) > 0 else None,
                    "latitude": coords[1] if len(coords) > 1 else None,
                    "date": item.get("timestamp"),
                    "data_mode": item.get("data_mode"),
                }
            )
        return results

    async def get_platform_metadata(self, wmo_number: int) -> dict | None:
        """Get metadata for a single float platform by WMO number."""
        params = {"platform": str(wmo_number)}
        data = await self._get("/argo/meta", params=params)
        if not data or len(data) == 0:
            return None

        meta = data[0] if isinstance(data, list) else data
        return self._parse_platform_meta(meta, wmo_number)

    async def list_floats_in_region(
        self,
        lon_min: float,
        lon_max: float,
        lat_min: float,
        lat_max: float,
        polygon: list[list[float]] | None = None,
    ) -> list[dict]:
        """List unique floats in a geographic region."""
        if polygon:
            poly_str = str(polygon).replace(" ", "")
        else:
            poly_str = self._bbox_to_polygon(lon_min, lon_max, lat_min, lat_max)

        params: dict[str, Any] = {
            "polygon": poly_str,
            "compression": "minimal",
        }
        data = await self._get("/argo", params=params)
        if not data:
            return []

        # Deduplicate by WMO, keeping the most recent position
        seen: dict[int, dict] = {}
        for item in data:
            wmo = self._extract_wmo(item)
            if wmo is None:
                continue
            geoloc = item.get("geolocation", {})
            coords = geoloc.get("coordinates", [None, None])
            ts = item.get("timestamp")
            if wmo not in seen or (ts and ts > seen[wmo].get("most_recent_date", "")):
                seen[wmo] = {
                    "wmo_number": wmo,
                    "longitude": coords[0] if len(coords) > 0 else None,
                    "latitude": coords[1] if len(coords) > 1 else None,
                    "most_recent_date": ts,
                }
        return list(seen.values())

    async def get_float_trajectory(self, wmo_number: int) -> list[dict]:
        """Get the trajectory (position time-series) for a float."""
        params: dict[str, Any] = {"platform": str(wmo_number)}
        data = await self._get("/argotrajectories", params=params)
        if not data:
            return await self._trajectory_from_profiles(wmo_number)

        points: list[dict] = []
        items = data if isinstance(data, list) else [data]
        for item in items:
            geoloc = item.get("geolocation", {})
            coords = geoloc.get("coordinates", [None, None])
            points.append(
                {
                    "longitude": coords[0] if len(coords) > 0 else None,
                    "latitude": coords[1] if len(coords) > 1 else None,
                    "date": item.get("timestamp"),
                    "cycle": item.get("cycle_number") or self._extract_cycle(item),
                }
            )
        points.sort(key=lambda p: p.get("date") or "")
        return points

    async def _trajectory_from_profiles(self, wmo_number: int) -> list[dict]:
        """Reconstruct trajectory from profile positions as fallback."""
        params: dict[str, Any] = {
            "platform": str(wmo_number),
            "compression": "minimal",
        }
        data = await self._get("/argo", params=params)
        if not data:
            return []

        points: list[dict] = []
        for item in data:
            geoloc = item.get("geolocation", {})
            coords = geoloc.get("coordinates", [None, None])
            points.append(
                {
                    "longitude": coords[0] if len(coords) > 0 else None,
                    "latitude": coords[1] if len(coords) > 1 else None,
                    "date": item.get("timestamp"),
                    "cycle": self._extract_cycle(item),
                }
            )
        points.sort(key=lambda p: p.get("date") or "")
        return points

    # ------------------------------------------------------------------
    # Tier 2 — Data Retrieval
    # ------------------------------------------------------------------

    async def get_profile(
        self,
        wmo_number: int,
        cycle: int,
        parameters: list[str] | None = None,
        include_all_qc: bool = False,
    ) -> dict | None:
        """Get a single profile by WMO and cycle number."""
        profile_id = f"{wmo_number}_{cycle:03d}"
        params: dict[str, Any] = {"id": profile_id}
        if parameters:
            params["data"] = ",".join(parameters)

        data = await self._get("/argo", params=params)
        if not data:
            # Retry without zero-padding
            params["id"] = f"{wmo_number}_{cycle}"
            data = await self._get("/argo", params=params)
        if not data:
            return None

        items = data if isinstance(data, list) else [data]
        if not items:
            return None
        return self._parse_profile(items[0], include_all_qc)

    async def get_profiles_in_region(
        self,
        lon_min: float,
        lon_max: float,
        lat_min: float,
        lat_max: float,
        date_start: str | None = None,
        date_end: str | None = None,
        parameters: list[str] | None = None,
        max_results: int = 50,
        include_all_qc: bool = False,
    ) -> list[dict]:
        """Get full profile data for a region."""
        params: dict[str, Any] = {
            "polygon": self._bbox_to_polygon(lon_min, lon_max, lat_min, lat_max),
        }
        if date_start:
            params["startDate"] = self._fmt_date(date_start)
        if date_end:
            params["endDate"] = self._fmt_date(date_end)
        if parameters:
            params["data"] = ",".join(parameters)

        data = await self._get("/argo", params=params)
        if not data:
            return []

        results: list[dict] = []
        for item in data[:max_results]:
            parsed = self._parse_profile(item, include_all_qc)
            if parsed:
                results.append(parsed)
        return results

    async def get_bgc_profile(
        self,
        wmo_number: int,
        cycle: int,
        variables: list[str] | None = None,
        include_all_qc: bool = False,
    ) -> dict | None:
        """Get BGC profile data."""
        profile_id = f"{wmo_number}_{cycle:03d}"
        params: dict[str, Any] = {"id": profile_id}
        if variables:
            # Request specific BGC variables plus pressure
            params["data"] = ",".join(["pressure"] + list(variables))

        data = await self._get("/argo", params=params)
        if not data:
            params["id"] = f"{wmo_number}_{cycle}"
            data = await self._get("/argo", params=params)
        if not data:
            return None

        items = data if isinstance(data, list) else [data]
        if not items:
            return None
        return self._parse_bgc_profile(items[0], variables, include_all_qc)

    # ------------------------------------------------------------------
    # Tier 4 — QC
    # ------------------------------------------------------------------

    async def get_profiles_for_float(self, wmo_number: int) -> list[dict]:
        """Get all profiles for a float (used for QC summary)."""
        params: dict[str, Any] = {
            "platform": str(wmo_number),
            "compression": "minimal",
        }
        data = await self._get("/argo", params=params)
        if not data:
            return []
        return data if isinstance(data, list) else [data]

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_wmo(item: dict) -> int | None:
        """Extract WMO number from an Argovis record."""
        _id = item.get("_id", "")
        if "_" in str(_id):
            try:
                return int(str(_id).split("_")[0])
            except (ValueError, IndexError):
                pass
        metadata = item.get("metadata", [])
        if metadata and isinstance(metadata, list):
            for m in metadata:
                if isinstance(m, str):
                    # metadata IDs look like "6903091_m0"
                    wmo_part = str(m).split("_")[0]
                    if wmo_part.isdigit():
                        return int(wmo_part)
        platform = item.get("platform")
        if platform:
            try:
                return int(platform)
            except (ValueError, TypeError):
                pass
        return None

    @staticmethod
    def _extract_cycle(item: dict) -> int | None:
        """Extract cycle number from an Argovis record."""
        cycle = item.get("cycle_number")
        if cycle is not None:
            try:
                return int(cycle)
            except (ValueError, TypeError):
                pass
        _id = item.get("_id", "")
        if "_" in str(_id):
            try:
                return int(str(_id).split("_")[1])
            except (ValueError, IndexError):
                pass
        return None

    @staticmethod
    def _parse_platform_meta(meta: dict, wmo_number: int) -> dict:
        """Parse platform metadata from Argovis response."""
        return {
            "wmo_number": wmo_number,
            "dac": meta.get("data_center") or meta.get("institution"),
            "float_model": meta.get("platform_type"),
            "deployment_date": meta.get("date_updated_argovis"),
            "deployment_longitude": None,
            "deployment_latitude": None,
            "transmission_system": meta.get("positioning_system"),
            "sensors": meta.get("sensor", []) or [],
            "cycles": meta.get("cycle_number"),
            "most_recent_date": meta.get("most_recent_date"),
            "most_recent_longitude": meta.get("most_recent_lon"),
            "most_recent_latitude": meta.get("most_recent_lat"),
        }

    def _parse_profile(self, item: dict, include_all_qc: bool) -> dict | None:
        """Parse a full profile record using data_info + transposed data."""
        geoloc = item.get("geolocation", {})
        coords = geoloc.get("coordinates", [None, None])

        var_names, levels = self._inflate(item)

        if not include_all_qc and levels:
            filtered: list[dict] = []
            for level in levels:
                qc_ok = True
                for key, val in level.items():
                    if "_argoqc" in key and val is not None and val != 1:
                        qc_ok = False
                        break
                if qc_ok:
                    filtered.append(level)
            levels = filtered

        # Strip QC columns from the parameter list for cleanliness
        clean_params = [v for v in var_names if "_argoqc" not in v]

        wmo = self._extract_wmo(item)
        cycle = self._extract_cycle(item)

        return {
            "wmo_number": wmo,
            "cycle": cycle,
            "longitude": coords[0] if len(coords) > 0 else None,
            "latitude": coords[1] if len(coords) > 1 else None,
            "date": item.get("timestamp"),
            "data_mode": item.get("data_mode"),
            "parameters": clean_params,
            "levels": levels,
            "qc_filter_applied": not include_all_qc,
        }

    def _parse_bgc_profile(
        self,
        item: dict,
        variables: list[str] | None,
        include_all_qc: bool,
    ) -> dict | None:
        """Parse a BGC profile record."""
        geoloc = item.get("geolocation", {})
        coords = geoloc.get("coordinates", [None, None])

        var_names, raw_levels = self._inflate(item)

        levels: list[dict] = []
        for lvl in raw_levels:
            pressure = lvl.get("pressure") or lvl.get("pres")
            values: dict[str, float | None] = {}
            qc_flags: dict[str, int | None] = {}

            for key, val in lvl.items():
                if key.lower() in ("pressure", "pres"):
                    continue
                if "_argoqc" in key:
                    base = key.replace("_argoqc", "")
                    qc_flags[base] = val
                else:
                    if not variables or key in variables:
                        values[key] = val

            # Apply QC filter
            if not include_all_qc:
                filtered_vals: dict[str, float | None] = {}
                for k, v in values.items():
                    qc = qc_flags.get(k)
                    if qc is None or qc == 1:
                        filtered_vals[k] = v
                values = filtered_vals

            levels.append(
                {"pressure": pressure, "values": values, "qc_flags": qc_flags}
            )

        clean_vars = variables or [
            v for v in var_names
            if "_argoqc" not in v and v.lower() not in ("pressure", "pres")
        ]

        return {
            "wmo_number": self._extract_wmo(item),
            "cycle": self._extract_cycle(item),
            "longitude": coords[0] if len(coords) > 0 else None,
            "latitude": coords[1] if len(coords) > 1 else None,
            "date": item.get("timestamp"),
            "variables": clean_vars,
            "levels": levels,
            "qc_filter_applied": not include_all_qc,
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()
