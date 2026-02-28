"""Tests for the Argovis async client using fixture data."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from argo_mcp.argovis import ArgovisClient

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> list | dict:
    return json.loads((FIXTURES / name).read_text())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_client(fixture_name: str) -> ArgovisClient:
    """Create a client whose _get always returns a given fixture."""
    client = ArgovisClient.__new__(ArgovisClient)
    client._client = None  # not needed
    data = _load(fixture_name)
    client._get = AsyncMock(return_value=data)
    return client


# ---------------------------------------------------------------------------
# Inflate
# ---------------------------------------------------------------------------


class TestInflate:
    def test_inflate_transposes_data(self):
        item = {
            "data_info": [["pressure", "temperature", "salinity"], [], []],
            "data": [
                [5.0, 10.0, 20.0],
                [18.5, 18.4, 18.2],
                [35.4, 35.4, 35.4],
            ],
        }
        var_names, levels = ArgovisClient._inflate(item)
        assert var_names == ["pressure", "temperature", "salinity"]
        assert len(levels) == 3
        assert levels[0] == {"pressure": 5.0, "temperature": 18.5, "salinity": 35.4}
        assert levels[2]["pressure"] == 20.0

    def test_inflate_empty_data(self):
        var_names, levels = ArgovisClient._inflate({})
        assert var_names == []
        assert levels == []


# ---------------------------------------------------------------------------
# Tier 1 — Discovery
# ---------------------------------------------------------------------------


class TestSearchProfiles:
    @pytest.mark.asyncio
    async def test_search_returns_profiles(self):
        client = _mock_client("search_profiles.json")
        results = await client.search_profiles(-15, -10, 42, 45)
        assert len(results) == 3
        assert results[0]["wmo_number"] == 6903091
        assert results[0]["cycle"] == 42
        assert results[0]["longitude"] == -12.345
        assert results[0]["latitude"] == 43.567

    @pytest.mark.asyncio
    async def test_search_respects_max_results(self):
        client = _mock_client("search_profiles.json")
        results = await client.search_profiles(-15, -10, 42, 45, max_results=1)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_search_empty(self):
        client = ArgovisClient.__new__(ArgovisClient)
        client._client = None
        client._get = AsyncMock(return_value=None)
        results = await client.search_profiles(-15, -10, 42, 45)
        assert results == []


class TestGetPlatformMetadata:
    @pytest.mark.asyncio
    async def test_returns_metadata(self):
        client = _mock_client("platform_meta.json")
        meta = await client.get_platform_metadata(6903091)
        assert meta is not None
        assert meta["wmo_number"] == 6903091
        assert meta["dac"] == "IF"
        assert meta["float_model"] == "ARVOR"
        assert "CTD_PRES" in meta["sensors"]

    @pytest.mark.asyncio
    async def test_not_found(self):
        client = ArgovisClient.__new__(ArgovisClient)
        client._client = None
        client._get = AsyncMock(return_value=None)
        meta = await client.get_platform_metadata(9999999)
        assert meta is None


class TestListFloatsInRegion:
    @pytest.mark.asyncio
    async def test_deduplicates_by_wmo(self):
        client = _mock_client("search_profiles.json")
        floats = await client.list_floats_in_region(-15, -10, 42, 45)
        wmos = [f["wmo_number"] for f in floats]
        assert len(wmos) == len(set(wmos))
        assert 6903091 in wmos
        assert 4902550 in wmos


class TestGetFloatTrajectory:
    @pytest.mark.asyncio
    async def test_returns_sorted_points(self):
        client = _mock_client("trajectory.json")
        points = await client.get_float_trajectory(6903091)
        assert len(points) == 3
        dates = [p["date"] for p in points]
        assert dates == sorted(dates)
        assert points[0]["cycle"] == 1


# ---------------------------------------------------------------------------
# Tier 2 — Data Retrieval
# ---------------------------------------------------------------------------


class TestGetProfile:
    @pytest.mark.asyncio
    async def test_returns_inflated_profile(self):
        client = _mock_client("profile_data.json")
        profile = await client.get_profile(6903091, 42)
        assert profile is not None
        assert profile["wmo_number"] == 6903091
        assert profile["cycle"] == 42
        assert len(profile["levels"]) == 10
        # First level should have pressure 5.0, temp 18.5
        assert profile["levels"][0]["pressure"] == 5.0
        assert profile["levels"][0]["temperature"] == 18.5

    @pytest.mark.asyncio
    async def test_qc_filtering(self):
        client = _mock_client("profile_with_bad_qc.json")
        # With QC filter (default)
        profile = await client.get_profile(6903091, 42, include_all_qc=False)
        assert profile is not None
        # Levels with QC != 1 should be removed
        assert len(profile["levels"]) < 8
        assert profile["qc_filter_applied"] is True

    @pytest.mark.asyncio
    async def test_qc_filtering_disabled(self):
        client = _mock_client("profile_with_bad_qc.json")
        profile = await client.get_profile(6903091, 42, include_all_qc=True)
        assert profile is not None
        assert len(profile["levels"]) == 8
        assert profile["qc_filter_applied"] is False


class TestGetBGCProfile:
    @pytest.mark.asyncio
    async def test_returns_bgc_data(self):
        client = _mock_client("bgc_profile.json")
        profile = await client.get_bgc_profile(2902857, 1, variables=["doxy", "chla"])
        assert profile is not None
        assert profile["wmo_number"] == 2902857
        assert len(profile["levels"]) == 5
        assert "doxy" in profile["levels"][0]["values"]
        assert "chla" in profile["levels"][0]["values"]


# ---------------------------------------------------------------------------
# Helpers unit tests
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_fmt_date_adds_time(self):
        assert ArgovisClient._fmt_date("2024-01-15") == "2024-01-15T00:00:00Z"

    def test_fmt_date_adds_z(self):
        assert ArgovisClient._fmt_date("2024-01-15T12:00:00") == "2024-01-15T12:00:00Z"

    def test_fmt_date_already_complete(self):
        assert ArgovisClient._fmt_date("2024-01-15T12:00:00Z") == "2024-01-15T12:00:00Z"

    def test_bbox_to_polygon(self):
        poly = ArgovisClient._bbox_to_polygon(-15, -10, 42, 45)
        assert "[[-15,42]" in poly
        assert "[-15,45]" in poly
        assert poly.startswith("[")
        assert poly.endswith("]")

    def test_extract_wmo_from_id(self):
        assert ArgovisClient._extract_wmo({"_id": "6903091_042"}) == 6903091

    def test_extract_wmo_from_metadata(self):
        assert ArgovisClient._extract_wmo({"metadata": ["6903091_m0"]}) == 6903091

    def test_extract_cycle_from_cycle_number(self):
        assert ArgovisClient._extract_cycle({"cycle_number": 42}) == 42

    def test_extract_cycle_from_id(self):
        assert ArgovisClient._extract_cycle({"_id": "6903091_042"}) == 42
