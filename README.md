# 🗺️ The Brownfield Cartographer

A multi-agent codebase intelligence system that ingests any GitHub repository (or local path) and produces a living, queryable knowledge graph of the system's architecture, data flows, and semantic structure.

## Quick Start

### Installation

```bash
# Clone this repo
git clone <your-repo-url>
cd brownfield-cartographer

# Install with uv
uv venv
uv sync

# Or with pip
pip install -e .
```

## Usage

```bash
# Analyze a local codebase
python -m src.cli analyze /path/to/target/repo

# Analyze a GitHub repository
python -m src.cli analyze https://github.com/dbt-labs/jaffle-shop.git

# With custom output directory
python -m src.cli analyze /path/to/repo -o ./my-output

# Verbose mode
python -m src.cli analyze /path/to/repo -v
```

## Outputs
After analysis, artifacts are written to `.cartography/`:

- **module_graph.json** — Module import graph with PageRank scores, git velocity, dead code candidates
- **lineage_graph.json** — Data lineage DAG with table dependencies across Python/SQL/YAML

## Architecture
The system consists of specialized agents:

### Surveyor Agent: Static structure analysis
- Multi-language AST parsing (Python, SQL, YAML)
- Module import graph with PageRank centrality
- Structural metadata extraction

### Hydrologist Agent: Data lineage analysis
- SQL dependency extraction via `sqlglot`
- Python data flow detection (pandas, SQLAlchemy, PySpark)
- Airflow/dbt YAML config parsing
- Blast radius computation and source/sink identification

## Dependencies
- **Python 3.11+**
- **tree-sitter & tree-sitter-python** (AST parsing)
- **sqlglot** (SQL dependency extraction)
- **networkx** (graph algorithms)
- **pydantic v2** (typed data models)
- **click** (CLI framework)
- **rich** (console output)
- **pyyaml** (YAML parsing)
- **gitpython** (git operations)
