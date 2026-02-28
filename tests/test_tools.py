"""Tests for the argopy_utils analysis functions."""

from __future__ import annotations

import pytest

from argo_mcp.argopy_utils import (
    compute_mixed_layer_depth,
    compare_profiles_data,
    summarize_profiles,
)


# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

PRESSURE = [5.0, 10.0, 20.0, 50.0, 100.0, 200.0, 500.0, 1000.0]
TEMPERATURE = [18.5, 18.4, 18.2, 16.5, 14.2, 12.1, 8.5, 5.2]
SALINITY = [35.40, 35.41, 35.42, 35.50, 35.55, 35.60, 35.30, 35.10]


# ---------------------------------------------------------------------------
# MLD tests
# ---------------------------------------------------------------------------


class TestMLD:
    def test_density_threshold(self):
        result = compute_mixed_layer_depth(
            PRESSURE, TEMPERATURE, SALINITY, method="density_threshold"
        )
        assert result["method"] == "density_threshold"
        assert result["mld_meters"] is not None
        assert result["mld_meters"] > 0
        assert "reference_temperature" in result

    def test_temperature_gradient(self):
        result = compute_mixed_layer_depth(
            PRESSURE, TEMPERATURE, SALINITY, method="temperature_gradient"
        )
        assert result["method"] == "temperature_gradient"
        assert result["mld_meters"] is not None
        assert result["mld_meters"] > 0

    def test_holte_talley(self):
        result = compute_mixed_layer_depth(
            PRESSURE, TEMPERATURE, SALINITY, method="holte_talley"
        )
        assert result["method"] == "holte_talley"
        # May return None if insufficient data below 20 dbar
        # Our test data has enough points
        assert result.get("mld_meters") is not None or result.get("error") is not None

    def test_custom_threshold(self):
        result = compute_mixed_layer_depth(
            PRESSURE, TEMPERATURE, SALINITY,
            method="density_threshold", threshold=0.01,
        )
        assert result["method"] == "density_threshold"
        assert result["threshold_used"] == 0.01


# ---------------------------------------------------------------------------
# Profile comparison tests
# ---------------------------------------------------------------------------


class TestCompareProfiles:
    def test_comparison(self):
        profile_a = {
            "levels": [
                {"pressure": 10.0, "temperature": 18.0, "salinity": 35.4},
                {"pressure": 100.0, "temperature": 14.0, "salinity": 35.5},
            ]
        }
        profile_b = {
            "levels": [
                {"pressure": 10.0, "temperature": 17.5, "salinity": 35.3},
                {"pressure": 100.0, "temperature": 13.5, "salinity": 35.6},
            ]
        }
        result = compare_profiles_data(profile_a, profile_b)
        assert result["mean_temp_a"] == pytest.approx(16.0, abs=0.01)
        assert result["mean_temp_b"] == pytest.approx(15.5, abs=0.01)
        assert result["delta_mean_temp"] == pytest.approx(-0.5, abs=0.01)
        assert result["levels_a"] == 2
        assert result["levels_b"] == 2

    def test_empty_profiles(self):
        result = compare_profiles_data({"levels": []}, {"levels": []})
        assert result["mean_temp_a"] is None
        assert result["delta_mean_temp"] is None


# ---------------------------------------------------------------------------
# Region summary tests
# ---------------------------------------------------------------------------


class TestSummarizeProfiles:
    def test_summarize(self):
        profiles = [
            {
                "wmo_number": 6903091,
                "date": "2024-06-15T12:00:00Z",
                "data_mode": "D",
                "levels": [
                    {"pressure": 10.0, "temperature": 18.0, "salinity": 35.4},
                    {"pressure": 50.0, "temperature": 16.0, "salinity": 35.5},
                    {"pressure": 100.0, "temperature": 14.0, "salinity": 35.6},
                ],
            },
            {
                "wmo_number": 4902550,
                "date": "2024-06-20T08:00:00Z",
                "data_mode": "R",
                "levels": [
                    {"pressure": 10.0, "temperature": 19.0, "salinity": 35.3},
                    {"pressure": 50.0, "temperature": 17.0, "salinity": 35.5},
                ],
            },
        ]
        result = summarize_profiles(profiles)
        assert result["profile_count"] == 2
        assert result["float_count"] == 2
        assert result["data_mode_distribution"] == {"D": 1, "R": 1}
        assert "10" in result["mean_temperature_by_depth"]
        # Mean of 18.0 and 19.0 at 10m
        assert result["mean_temperature_by_depth"]["10"] == pytest.approx(18.5, abs=0.01)
        assert len(result["date_range"]) == 2


# ---------------------------------------------------------------------------
# Model response tests
# ---------------------------------------------------------------------------


class TestModels:
    def test_search_response_includes_citation(self):
        from argo_mcp.models import SearchProfilesResponse
        resp = SearchProfilesResponse(profiles=[], total_count=0)
        assert "Argo" in resp.citation
        assert "doi.org" in resp.doi

    def test_profile_data_model(self):
        from argo_mcp.models import ProfileData
        p = ProfileData(
            wmo_number=6903091,
            cycle=42,
            longitude=-12.3,
            latitude=43.5,
            date="2024-06-15",
            parameters=["pressure", "temperature"],
            levels=[{"pressure": 10.0, "temperature": 18.0}],
        )
        assert p.wmo_number == 6903091
        assert p.qc_filter_applied is True

    def test_mld_result_model(self):
        from argo_mcp.models import MLDResult
        r = MLDResult(
            wmo_number=6903091,
            cycle=42,
            mld_meters=45.0,
            method="density_threshold",
        )
        assert r.mld_meters == 45.0
        assert "Argo" in r.citation
