# Project Brief: Argo Ocean Data MCP Server

## What We're Building

An MCP (Model Context Protocol) server in Python that makes the international Argo float dataset conversationally queryable by any MCP-compatible LLM client (Claude Desktop, Cursor, etc.). The server exposes tools for searching, retrieving, and analyzing Argo ocean profiling float data — temperature, salinity, pressure, and biogeochemical variables from ~4,000 autonomous floats worldwide.

## Backend Data Sources

Use a hybrid backend strategy:

### Primary: Argovis REST API

- **Base URL:** `https://argovis-api.colorado.edu`
- OpenAPI spec available at `/docs`
- Supports spatial/temporal queries, profile retrieval, platform metadata
- Returns JSON — ideal for MCP's request-response pattern
- Requires API key for heavy usage (free tier available)
- **Reference:** <https://argovis.colorado.edu/apiintro>

### Secondary: argopy (Python library)

- `pip install argopy`
- Wraps GDAC (Global Data Assembly Centre) NetCDF access
- Provides xarray/pandas integration for heavier computation
- **Use for:** MLD computation, anomaly detection, bulk data processing
- **Key classes:** `DataFetcher`, `ArgoFloat`, `ArgoIndex`
- **Docs:** <https://argopy.readthedocs.io/>

### Tertiary: Euro-Argo Fleet Monitoring API

- **Swagger:** <https://fleetmonitoring.euro-argo.eu/swagger-ui.html>
- Good for fleet-level metadata and operational status
- Use as fallback/enrichment source

## Tool Taxonomy

### Tier 1 — Discovery & Search (lightweight, high-frequency)

#### `search_profiles`

- **Inputs:** `lon_min`, `lon_max`, `lat_min`, `lat_max`, `date_start`, `date_end`, `max_results`
- **Returns:** list of profile metadata (WMO, cycle, position, date, data_mode)
- **Backend:** Argovis

#### `get_float_metadata`

- **Inputs:** `wmo_number`
- **Returns:** platform metadata — deployment date/location, sensor manifest, DAC, float model, transmission system
- **Backend:** Argovis or Euro-Argo

#### `list_floats_in_region`

- **Inputs:** `polygon` (list of lon/lat pairs) or bounding box, `active_only` flag
- **Returns:** enumeration of floats with latest position and status
- **Backend:** Argovis

#### `get_float_trajectory`

- **Inputs:** `wmo_number`
- **Returns:** time-ordered position series with dates
- **Backend:** Argovis

### Tier 2 — Data Retrieval (returns measurement data)

#### `get_profile`

- **Inputs:** `wmo_number`, `cycle`, `parameters` (optional filter list)
- **Returns:** full T/S/P profile arrays with depth, QC-filtered by default (flag=1 only)
- **Backend:** Argovis, fall back to argopy

#### `get_profiles_in_region`

- **Inputs:** `region` (bbox), `time_range`, `parameters`, `max_results`
- **Returns:** bulk profile data for spatial analysis
- **Backend:** Argovis

#### `get_bgc_profile`

- **Inputs:** `wmo_number`, `cycle`, `variables` (`DOXY`, `CHLA`, `BBP700`, `PH_IN_SITU`, `NITRATE`, etc.)
- **Returns:** biogeochemical measurements with associated QC
- **Backend:** Argovis or argopy

### Tier 3 — Analysis (computed outputs, differentiates from raw API wrapper)

#### `compute_mixed_layer_depth`

- **Inputs:** `wmo_number`, `cycle`, `method` (`'density_threshold'` | `'temperature_gradient'` | `'holte_talley'`), `threshold`
- **Returns:** MLD in meters, method used, reference values
- **Backend:** argopy (needs array computation)

#### `compare_profiles`

- **Inputs:** `wmo_number`, `cycle_a`, `cycle_b`
- **Returns:** side-by-side T/S/P comparison, delta summary
- **Backend:** Argovis for retrieval, local computation for comparison

#### `summarize_region`

- **Inputs:** `region`, `time_range`
- **Returns:** aggregate stats — profile count, float count, mean T/S at standard depths, data mode distribution
- **Backend:** Argovis + local aggregation

### Tier 4 — QC-Aware Tools

#### `get_qc_summary`

- **Inputs:** `wmo_number`
- **Returns:** data mode per cycle (R/A/D), known issues, QC flag distribution
- **Backend:** Argovis or argopy

#### `get_adjusted_profile`

- **Inputs:** `wmo_number`, `cycle`
- **Returns:** delayed-mode adjusted data only (QC flag=1, `ADJUSTED_PRES_ERROR` < 20 dbar)
- **Backend:** argopy (accesses the full NetCDF with adjusted fields)

## Critical Design Requirements

### QC-by-default philosophy

All data retrieval tools should return QC-filtered data (flag=1) by default. Include an `include_all_qc: bool = False` parameter to override. Users who want real-time unfiltered data must explicitly opt in. **This is non-negotiable for scientific credibility.**

### Argo citation compliance

Every data response should include or make available the standard Argo citation:

> "These data were collected and made freely available by the international Argo project and the national programs that contribute to it."

And the DOI: <https://doi.org/10.17882/42182>

### BGC-Argo parameter awareness

The tool schemas must accommodate the expanding BGC variable set. Use Argo Reference Table R03 parameter names. Core parameters: `TEMP`, `PSAL`, `PRES`. BGC parameters: `DOXY`, `CHLA`, `BBP700`, `PH_IN_SITU_TOTAL`, `NITRATE`, `DOWN_IRRADIANCE`, `CDOM`.

### Structured output schemas

Use the MCP SDK's structured output support (`outputSchema` on tools) wherever possible. Return well-typed dictionaries that downstream LLMs can reason about, not free-text descriptions of data.

### Error handling

- Argovis API can be slow or return 5xx — implement retries with backoff
- Float/cycle combinations that don't exist should return clear "not found" messages, not stack traces
- Rate limiting awareness — Argovis has usage limits; respect them and inform the user

## Project Structure

### Technology Stack

- Python 3.11+ with `uv` for project management
- MCP Python SDK (`mcp[cli]` >= 1.2.0) with FastMCP
- `httpx` for async HTTP to Argovis
- `argopy` for GDAC/NetCDF operations
- `numpy` for numerical computations (MLD, anomaly detection)
- `pydantic` for response models (optional but recommended)

### Transport

- **Default:** stdio (for Claude Desktop / Cursor local use)
- **Optional:** Streamable HTTP for team/remote deployment
- Both should work without code changes — FastMCP handles this

### Directory Layout

```
argo-mcp/
├── pyproject.toml          # uv-managed, dependencies: mcp[cli], httpx, argopy, numpy
├── README.md               # Setup, usage, tool documentation
├── src/
│   └── argo_mcp/
│       ├── __init__.py
│       ├── server.py       # FastMCP server, tool definitions
│       ├── argovis.py      # Argovis API client (async, httpx)
│       ├── argopy_utils.py # argopy wrapper functions for analysis tools
│       ├── models.py       # Pydantic models for structured responses
│       └── config.py       # API keys, base URLs, defaults
├── tests/
│   ├── test_argovis.py
│   ├── test_tools.py
│   └── fixtures/           # Sample API responses for offline testing
└── .env.example            # ARGOVIS_API_KEY template
```

## Getting Started

1. Scaffold the project with `uv init`
1. Implement the Argovis async client first (`argovis.py`)
1. Wire up Tier 1 tools (`search_profiles`, `get_float_metadata`) — these are the quickest wins
1. Test with MCP Inspector (`mcp dev src/argo_mcp/server.py`)
1. Add Tier 2 retrieval tools
1. Add argopy-backed Tier 3 analysis tools
1. Write tests using fixture data

## Testing Strategy

- Use MCP Inspector for interactive tool testing during development
- Save real Argovis API responses as JSON fixtures for offline/CI testing
- Test with known float WMO numbers (e.g., `6903091` — Coriolis float with good data coverage)
- Validate QC filtering actually works by comparing filtered vs unfiltered output

## Context

This project is being developed at **RBR Global** ([rbr-global.com](https://rbr-global.com)), a Canadian oceanographic instrument manufacturer. The Argo MCP server has potential applications for:

- Cross-referencing Argo profiles with RBR instrument deployments for validation
- Supporting the SEA-CORE seagrass ecosystem automation project (JPI Oceans funded)
- General community contribution to the oceanographic data accessibility ecosystem

The team uses a mix of Mac and Windows, so cross-platform compatibility matters.
