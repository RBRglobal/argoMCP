# Argo Ocean Data MCP Server

An [MCP](https://modelcontextprotocol.io/) server that makes the international [Argo float](https://argo.ucsd.edu/) dataset conversationally queryable from any MCP-compatible client (Claude Desktop, Cursor, etc.).

Query temperature, salinity, pressure, and biogeochemical variables from ~4,000 autonomous ocean profiling floats worldwide.

## Quick Start

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager

### Install

```bash
git clone https://github.com/RBRglobal/argoMCP.git
cd argoMCP
uv sync
```

### Configure (optional)

Copy the environment template and add your Argovis API key for heavy usage:

```bash
cp .env.example .env
# Edit .env and add your ARGOVIS_API_KEY
```

Free API keys are available at https://argovis-keygen.colorado.edu/

### Run

```bash
# stdio transport (for Claude Desktop / Cursor)
uv run argo-mcp

# Or with MCP Inspector for development
uv run mcp dev src/argo_mcp/server.py
```

### Claude Desktop Configuration

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "argo-mcp": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/argoMCP", "argo-mcp"],
      "env": {
        "ARGOVIS_API_KEY": "your-key-here"
      }
    }
  }
}
```

## Tools

### Tier 1 -- Discovery & Search

| Tool | Description |
|---|---|
| `search_profiles` | Search profiles by bounding box and time range |
| `get_float_metadata` | Get platform metadata (sensors, DAC, model) by WMO number |
| `list_floats_in_region` | List unique floats in a geographic region |
| `get_float_trajectory` | Get chronological position history for a float |

### Tier 2 -- Data Retrieval

| Tool | Description |
|---|---|
| `get_profile` | Retrieve full T/S/P profile for a float and cycle |
| `get_profiles_in_region` | Bulk profile data for spatial analysis |
| `get_bgc_profile` | Biogeochemical measurements (DOXY, CHLA, BBP700, etc.) |

### Tier 3 -- Analysis

| Tool | Description |
|---|---|
| `compute_mixed_layer_depth` | Compute MLD using density threshold, temperature gradient, or Holte-Talley methods |
| `compare_profiles` | Side-by-side comparison of two cycles from the same float |
| `summarize_region` | Aggregate statistics (profile count, mean T/S at standard depths) |

### Tier 4 -- QC-Aware

| Tool | Description |
|---|---|
| `get_qc_summary` | Data mode and QC flag distribution for all cycles of a float |
| `get_adjusted_profile` | Delayed-mode adjusted data only (QC flag=1) |

## QC-by-Default

All data retrieval tools return QC-filtered data (flag=1) by default. Pass `include_all_qc=True` to get unfiltered measurements. This is non-negotiable for scientific credibility.

## Data Sources

- **Primary:** [Argovis REST API](https://argovis-api.colorado.edu) -- spatial/temporal queries, profile retrieval, metadata
- **Secondary:** [argopy](https://argopy.readthedocs.io/) -- GDAC NetCDF access for analysis tools
- **Tertiary:** [Euro-Argo Fleet Monitoring](https://fleetmonitoring.euro-argo.eu/) -- fleet metadata enrichment

## Argo Citation

> These data were collected and made freely available by the international Argo project and the national programs that contribute to it.

DOI: https://doi.org/10.17882/42182

## Testing

```bash
uv run pytest tests/ -v
```

Tests use JSON fixture data from real Argovis API responses for offline/CI testing.

## Project Structure

```
argoMCP/
├── pyproject.toml
├── src/argo_mcp/
│   ├── server.py          # FastMCP server with all tool definitions
│   ├── argovis.py         # Async Argovis API client (httpx)
│   ├── argopy_utils.py    # Analysis functions (MLD, comparison, summary)
│   ├── models.py          # Pydantic response models
│   └── config.py          # Configuration and constants
├── tests/
│   ├── test_argovis.py    # Client and parsing tests
│   ├── test_tools.py      # Analysis and model tests
│   └── fixtures/          # Sample API responses
└── .env.example
```

## License

See [LICENSE](LICENSE).
