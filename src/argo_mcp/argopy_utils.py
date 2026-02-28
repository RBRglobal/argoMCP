"""Wrapper functions around argopy for Tier 3 analysis and Tier 4 QC tools.

argopy accesses GDAC NetCDF files and provides xarray/pandas integration
for heavier computation (MLD, anomaly detection, adjusted profiles).
"""

from __future__ import annotations

import logging
from typing import Literal

import numpy as np

logger = logging.getLogger(__name__)


def _import_argopy():
    """Lazy-import argopy so the server starts even if argopy is not installed."""
    try:
        import argopy  # noqa: F811
        return argopy
    except ImportError:
        logger.warning("argopy is not installed — Tier 3/4 tools will be limited")
        return None


# ---------------------------------------------------------------------------
# Mixed Layer Depth computation
# ---------------------------------------------------------------------------

def compute_mld_density_threshold(
    pressure: list[float],
    temperature: list[float],
    salinity: list[float],
    threshold: float = 0.03,
    ref_pressure: float = 10.0,
) -> dict:
    """Compute MLD using the density threshold method.

    Finds the shallowest depth where potential density exceeds the
    reference density (at ref_pressure) by more than *threshold* kg/m³.
    """
    pres = np.array(pressure, dtype=float)
    temp = np.array(temperature, dtype=float)
    sal = np.array(salinity, dtype=float)

    # Simple potential density approximation (UNESCO EOS-80 simplified)
    density = _potential_density(temp, sal, pres)

    # Find reference density at ref_pressure
    ref_idx = np.argmin(np.abs(pres - ref_pressure))
    ref_density = density[ref_idx]
    ref_temp = float(temp[ref_idx])

    # Find where density exceeds threshold
    for i in range(ref_idx + 1, len(density)):
        if density[i] - ref_density > threshold:
            mld = float(pres[i])
            return {
                "mld_meters": mld,
                "method": "density_threshold",
                "reference_pressure": float(ref_pressure),
                "reference_temperature": ref_temp,
                "reference_density": float(ref_density),
                "threshold_used": threshold,
            }

    return {
        "mld_meters": None,
        "method": "density_threshold",
        "reference_pressure": float(ref_pressure),
        "reference_temperature": ref_temp,
        "reference_density": float(ref_density),
        "threshold_used": threshold,
        "error": "MLD not found within profile depth range",
    }


def compute_mld_temperature_gradient(
    pressure: list[float],
    temperature: list[float],
    threshold: float = 0.2,
    ref_pressure: float = 10.0,
) -> dict:
    """Compute MLD using the temperature gradient method.

    Finds the shallowest depth where temperature differs from the
    reference temperature by more than *threshold* degrees C.
    """
    pres = np.array(pressure, dtype=float)
    temp = np.array(temperature, dtype=float)

    ref_idx = np.argmin(np.abs(pres - ref_pressure))
    ref_temp = float(temp[ref_idx])

    for i in range(ref_idx + 1, len(temp)):
        if abs(temp[i] - ref_temp) > threshold:
            mld = float(pres[i])
            return {
                "mld_meters": mld,
                "method": "temperature_gradient",
                "reference_pressure": float(ref_pressure),
                "reference_temperature": ref_temp,
                "threshold_used": threshold,
            }

    return {
        "mld_meters": None,
        "method": "temperature_gradient",
        "reference_pressure": float(ref_pressure),
        "reference_temperature": ref_temp,
        "threshold_used": threshold,
        "error": "MLD not found within profile depth range",
    }


def compute_mld_holte_talley(
    pressure: list[float],
    temperature: list[float],
    salinity: list[float],
) -> dict:
    """Compute MLD using a simplified Holte & Talley (2009) algorithm.

    Uses the density algorithm subset: finds the maximum of the
    second derivative of density with respect to pressure in the
    upper 1000 dbar.
    """
    pres = np.array(pressure, dtype=float)
    temp = np.array(temperature, dtype=float)
    sal = np.array(salinity, dtype=float)

    mask = pres <= 1000
    pres = pres[mask]
    temp = temp[mask]
    sal = sal[mask]

    if len(pres) < 5:
        return {
            "mld_meters": None,
            "method": "holte_talley",
            "error": "Insufficient data points for Holte-Talley method",
        }

    density = _potential_density(temp, sal, pres)

    # Second derivative of density w.r.t. pressure
    d2rho_dp2 = np.gradient(np.gradient(density, pres), pres)

    # Find maximum curvature below 20 dbar (skip surface noise)
    shallow_mask = pres >= 20
    if not np.any(shallow_mask):
        return {
            "mld_meters": None,
            "method": "holte_talley",
            "error": "No data below 20 dbar",
        }

    sub_d2 = d2rho_dp2[shallow_mask]
    sub_pres = pres[shallow_mask]
    max_idx = np.argmax(np.abs(sub_d2))
    mld = float(sub_pres[max_idx])

    ref_idx = np.argmin(np.abs(pres - 10.0))
    return {
        "mld_meters": mld,
        "method": "holte_talley",
        "reference_pressure": 10.0,
        "reference_temperature": float(temp[ref_idx]) if ref_idx < len(temp) else None,
        "reference_density": float(density[ref_idx]) if ref_idx < len(density) else None,
    }


def compute_mixed_layer_depth(
    pressure: list[float],
    temperature: list[float],
    salinity: list[float],
    method: Literal["density_threshold", "temperature_gradient", "holte_talley"] = "density_threshold",
    threshold: float | None = None,
) -> dict:
    """Dispatch MLD computation to the chosen method."""
    if method == "density_threshold":
        return compute_mld_density_threshold(
            pressure, temperature, salinity, threshold=threshold or 0.03
        )
    elif method == "temperature_gradient":
        return compute_mld_temperature_gradient(
            pressure, temperature, threshold=threshold or 0.2
        )
    elif method == "holte_talley":
        return compute_mld_holte_talley(pressure, temperature, salinity)
    else:
        return {"error": f"Unknown method: {method}"}


# ---------------------------------------------------------------------------
# Profile comparison helpers
# ---------------------------------------------------------------------------

def compare_profiles_data(
    profile_a: dict,
    profile_b: dict,
) -> dict:
    """Compare two profiles and compute delta summary."""
    def _extract_arrays(profile: dict):
        levels = profile.get("levels", [])
        temps, sals, pres_vals = [], [], []
        for lvl in levels:
            if isinstance(lvl, dict):
                t = lvl.get("temperature") or lvl.get("TEMP")
                s = lvl.get("salinity") or lvl.get("PSAL")
                p = lvl.get("pressure") or lvl.get("PRES")
                if t is not None:
                    temps.append(float(t))
                if s is not None:
                    sals.append(float(s))
                if p is not None:
                    pres_vals.append(float(p))
        return temps, sals, pres_vals

    temps_a, sals_a, pres_a = _extract_arrays(profile_a)
    temps_b, sals_b, pres_b = _extract_arrays(profile_b)

    mean_t_a = float(np.mean(temps_a)) if temps_a else None
    mean_t_b = float(np.mean(temps_b)) if temps_b else None
    mean_s_a = float(np.mean(sals_a)) if sals_a else None
    mean_s_b = float(np.mean(sals_b)) if sals_b else None

    return {
        "mean_temp_a": mean_t_a,
        "mean_temp_b": mean_t_b,
        "mean_sal_a": mean_s_a,
        "mean_sal_b": mean_s_b,
        "delta_mean_temp": round(mean_t_b - mean_t_a, 4) if mean_t_a is not None and mean_t_b is not None else None,
        "delta_mean_sal": round(mean_s_b - mean_s_a, 4) if mean_s_a is not None and mean_s_b is not None else None,
        "depth_range_a": [min(pres_a), max(pres_a)] if pres_a else [],
        "depth_range_b": [min(pres_b), max(pres_b)] if pres_b else [],
        "levels_a": len(temps_a),
        "levels_b": len(temps_b),
    }


# ---------------------------------------------------------------------------
# Region summary helpers
# ---------------------------------------------------------------------------

STANDARD_DEPTHS = [10, 50, 100, 200, 500, 1000, 1500, 2000]


def summarize_profiles(profiles: list[dict]) -> dict:
    """Compute aggregate statistics across a set of profiles."""
    wmos: set[int] = set()
    data_modes: dict[str, int] = {}
    temp_by_depth: dict[str, list[float]] = {str(d): [] for d in STANDARD_DEPTHS}
    sal_by_depth: dict[str, list[float]] = {str(d): [] for d in STANDARD_DEPTHS}
    dates: list[str] = []

    for p in profiles:
        wmo = p.get("wmo_number")
        if wmo:
            wmos.add(int(wmo))
        dm = p.get("data_mode", "unknown")
        data_modes[dm] = data_modes.get(dm, 0) + 1
        dt = p.get("date")
        if dt:
            dates.append(dt)

        levels = p.get("levels", [])
        for lvl in levels:
            if not isinstance(lvl, dict):
                continue
            pres = lvl.get("pressure") or lvl.get("PRES")
            temp = lvl.get("temperature") or lvl.get("TEMP")
            sal = lvl.get("salinity") or lvl.get("PSAL")
            if pres is None:
                continue
            # Bin to nearest standard depth
            nearest = min(STANDARD_DEPTHS, key=lambda d: abs(d - float(pres)))
            if abs(float(pres) - nearest) < nearest * 0.3:
                if temp is not None:
                    temp_by_depth[str(nearest)].append(float(temp))
                if sal is not None:
                    sal_by_depth[str(nearest)].append(float(sal))

    mean_temp = {
        k: round(float(np.mean(v)), 3) for k, v in temp_by_depth.items() if v
    }
    mean_sal = {
        k: round(float(np.mean(v)), 3) for k, v in sal_by_depth.items() if v
    }
    dates.sort()

    return {
        "profile_count": len(profiles),
        "float_count": len(wmos),
        "data_mode_distribution": data_modes,
        "mean_temperature_by_depth": mean_temp,
        "mean_salinity_by_depth": mean_sal,
        "date_range": [dates[0], dates[-1]] if dates else [],
    }


# ---------------------------------------------------------------------------
# Adjusted profile retrieval via argopy
# ---------------------------------------------------------------------------

def fetch_adjusted_profile_argopy(wmo_number: int, cycle: int) -> dict | None:
    """Fetch delayed-mode adjusted data using argopy.

    Returns profile with only adjusted fields and QC flag=1.
    """
    argopy = _import_argopy()
    if argopy is None:
        return None

    try:
        fetcher = argopy.DataFetcher(src="gdac", mode="expert").float(
            wmo_number, CYC=[cycle]
        )
        ds = fetcher.to_xarray()

        # Filter to adjusted data with good QC
        variables = []
        levels: list[dict] = []
        for var in ds.data_vars:
            if "ADJUSTED" in str(var) and "_QC" not in str(var) and "_ERROR" not in str(var):
                variables.append(str(var))

        n_levels = ds.dims.get("N_LEVELS", ds.dims.get("N_PROF", 0))
        for i in range(n_levels):
            level: dict = {}
            good = True
            for var in variables:
                qc_var = f"{var}_QC"
                if qc_var in ds:
                    qc_val = int(ds[qc_var].values.flat[i]) if i < ds[qc_var].size else None
                    if qc_val is not None and qc_val != 1:
                        good = False
                        continue
                val = float(ds[var].values.flat[i]) if i < ds[var].size else None
                if val is not None and not np.isnan(val):
                    level[var] = val
            if good and level:
                levels.append(level)

        return {
            "parameters": variables,
            "levels": levels,
            "adjusted": True,
        }
    except Exception as e:
        logger.warning("argopy fetch failed for WMO %d cycle %d: %s", wmo_number, cycle, e)
        return None


# ---------------------------------------------------------------------------
# Density utilities
# ---------------------------------------------------------------------------

def _potential_density(
    temperature: np.ndarray,
    salinity: np.ndarray,
    pressure: np.ndarray,
) -> np.ndarray:
    """Simplified potential density calculation (UNESCO EOS-80 approximation).

    Returns sigma-theta (potential density anomaly) in kg/m³.
    For production use, consider using gsw (TEOS-10).
    """
    # Simplified linear EOS
    rho_0 = 1025.0
    alpha = 2.0e-4  # thermal expansion coefficient (1/K)
    beta = 7.5e-4   # haline contraction coefficient (1/PSU)
    T_ref = 10.0
    S_ref = 35.0

    sigma = rho_0 * (1 - alpha * (temperature - T_ref) + beta * (salinity - S_ref))
    return sigma
