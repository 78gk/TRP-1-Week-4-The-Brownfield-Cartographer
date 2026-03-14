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

### Querying an analyzed codebase

```bash
# Launch interactive navigator
python -m src.cli query --graph-dir .cartography/jaffle_shop
```

### Incremental analysis

```bash
# Re-run analysis using the previous run metadata
python -m src.cli analyze /path/to/repo --incremental
```

## Project Structure

```text
src/
	cli.py
	orchestrator.py
	agents/
		surveyor.py
		hydrologist.py
		semanticist.py
		archivist.py
		navigator.py
	analyzers/
		dag_config_parser.py
		sql_lineage.py
		tree_sitter_analyzer.py
	graph/
		knowledge_graph.py
	models/
		edges.py
		nodes.py
	utils/
		token_budget.py
		llm_client.py
```

## Output Artifacts

After analysis, artifacts are written to the selected output directory, typically `.cartography/`.

| Artifact | Purpose |
|----------|---------|
| `module_graph.json` | Serialized structural graph for modules and functions, including architectural metadata. |
| `lineage_graph.json` | Serialized lineage graph covering datasets, transformations, and config-driven flow. |
| `CODEBASE.md` | Living architecture summary for onboarding, navigation, and AI-assisted context injection. |
| `onboarding_brief.md` | Day-one summary of critical flows, outputs, and architectural hotspots. |
| `cartography_trace.jsonl` | Execution trace log capturing generated artifacts and evidence provenance. |

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

### Semanticist Agent: Semantic understanding and fallback reasoning
- Generates module purpose statements when an LLM is configured
- Detects documentation drift against implementation behavior
- Clusters modules into business domains
- Falls back gracefully when no API key is configured

### Archivist Agent: Artifact generation and audit trail
- Produces `CODEBASE.md` and `onboarding_brief.md`
- Writes `cartography_trace.jsonl` for traceability
- Consolidates outputs from the other agents into durable artifacts

### Navigator Agent: Interactive query interface
- Loads previously generated graph artifacts
- Routes natural-language questions to structural and lineage tools
- Supports implementation lookup, lineage tracing, blast-radius analysis, and module explanation

## Query Examples

- `Where is the revenue calculation logic?`
- `What produces the daily_active_users table?`
- `What breaks if I change src/transforms/revenue.py?`
- `Explain what src/ingestion/kafka_consumer.py does`

## Incremental Mode

The `--incremental` flag reuses metadata from the prior run to detect changed files since the last analyzed commit. This allows the pipeline to skip the initial full-history assumption and operate in a faster update mode when the target repository is under Git.

```bash
python -m src.cli analyze /path/to/repo --output .cartography/my_repo --incremental
```

If no previous run metadata is available, the orchestrator falls back to a full analysis automatically.

## Target Codebases Tested

- `dbt-labs/jaffle_shop`
- `dbt-labs/jaffle-shop-classic`

## Environment Variables

- `GEMINI_API_KEY` or `GOOGLE_API_KEY` (optional, enables semantic analysis and richer query answers)

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
