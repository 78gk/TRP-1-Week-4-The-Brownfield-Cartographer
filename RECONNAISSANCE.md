# RECONNAISSANCE.md: ol-data-platform Codebase Audit

This report documents the manual reconnaissance of the `mitodl/ol-data-platform` repository, answering the Five FDE Day-One Questions and identifying the concrete pain points that a Brownfield Cartographer system should remove.

## 0. Target Qualification

Why this target was selected:
- It is a real brownfield data platform used to power MIT Open Learning data services.
- It visibly contains both Python orchestration code and SQL transformation code in the same repository.
- It is comfortably above the size threshold, with multiple Dagster code locations, shared Python packages, utility scripts, and a full dbt project.
- It represents the mixed-stack architecture the assignment is aiming at: Python ingestion and orchestration, dbt SQL transformations, warehouse configuration, and downstream analytics surfaces.

## 1. Primary Data Ingestion Path
The primary ingestion path is **Python-orchestrated landing into the raw lakehouse, followed by dbt SQL transformation**.
- **Source**: Operational data is ingested through Python-based loaders and orchestrators rather than through SQL alone.
- **Mechanism**: `dg_projects/data_loading/data_loading/defs/edxorg_s3_ingest/loads.py` defines a `dlt.pipeline` named `edxorg_s3` that writes environment-specific outputs into filesystem or S3 destinations.
- **Concrete file-level evidence**: `dg_projects/data_loading/data_loading/defs/edxorg_s3_ingest/README.md` documents that production writes Iceberg tables to `s3://ol-data-lake-raw-production/edxorg` and registers them in the `ol_warehouse_production_raw` Glue database.
- **Transformation handoff**: `dg_projects/lakehouse/lakehouse/definitions.py` wires the dbt project into the lakehouse code location, and `dg_projects/lakehouse/lakehouse/assets/lakehouse/dbt.py` exposes the `full_dbt_project` asset that builds the SQL transformation layer from `src/ol_dbt`.

## 2. Most Critical Output Datasets Or Endpoints
The most critical outputs identified during manual exploration are:
1. **Raw Iceberg tables in `ol_warehouse_production_raw`**: this is the first durable landing zone for ingested source data.
2. **The dbt transformation output rooted in `src/ol_dbt`**: `dg_projects/lakehouse/lakehouse/assets/lakehouse/dbt.py` materializes the project as the `full_dbt_project` asset.
3. **Reporting and mart-layer warehouse schemas**: `bin/dbt-local-dev.py` defines dependency-order registration for `raw`, `staging`, `intermediate`, `dimensional`, `mart`, `reporting`, and `external` databases.
4. **Superset-backed datasets**: `AGENTS.md` documents automatic Superset dataset refresh when dbt models change.
5. **`student_risk_probability_data_export_job`**: `dg_projects/student_risk_probability/student_risk_probability/definitions.py` defines a concrete downstream analytics export path.

## 3. Blast Radius Analysis: `full_dbt_project` failure
If `dg_projects/lakehouse/lakehouse/assets/lakehouse/dbt.py` fails at the `full_dbt_project` asset:
1. **Direct Impact**: the warehouse transformation layer in `src/ol_dbt` stops materializing.
2. **Downstream Impact**: `dg_projects/lakehouse/lakehouse/definitions.py` cannot deliver a current Dagster lakehouse asset graph for downstream consumers.
3. **Serving Impact**: Superset-backed datasets stop refreshing because `AGENTS.md` ties them to dbt model updates.
4. **Business Result**: downstream jobs such as `student_risk_probability_data_export_job` risk exporting stale or missing warehouse-derived data.

## 4. Business Logic: Concentrated vs. Distributed
- **Distributed orchestration logic**: Python orchestration is spread across multiple Dagster code locations under `dg_projects/`, shared resources under `packages/ol-orchestrate-lib`, and ingestion utilities under `bin/`.
- **Distributed environment logic**: data landing and environment-specific behavior are split across files such as `dg_projects/data_loading/data_loading/defs/edxorg_s3_ingest/loads.py` and `dg_projects/lakehouse/lakehouse/definitions.py`.
- **Concentrated business logic**: heavier reusable business semantics are concentrated in the dbt project under `src/ol_dbt`, especially the `models/intermediate/`, `models/marts/`, and `models/reporting/` layers documented in `AGENTS.md` and `src/ol_dbt/README.md`.
- **Coordination point**: `dg_projects/lakehouse/lakehouse/assets/lakehouse/dbt.py` is the key bridge where SQL models become orchestrated platform assets.

## 5. Most Frequent Changes (Last 90 Days)
This answer is a manual inference based on visible recent repository activity, not a full `git log` audit.
- **`src/ol_dbt/...` model files** are likely high-churn because the repository landing page showed a same-day fix to model logic: “Fix mitxonline program product and order models.”
- **`bin/dbt-local-dev.py`** is likely high-churn because the repository recently added a DuckDB plus Iceberg local dbt workflow and this script is central to that developer path.
- **`dg_projects/data_loading/...`** is likely high-churn because the repository recently added dlt-based EdX.org S3 ingestion.

Strict scoring note:
- A stricter version of this answer would still benefit from attaching an actual `git log` sample or validated Cartographer velocity output.

---

## DIFFICULTY ANALYSIS

### Manual Pain Points
- **Python-to-SQL boundary tracing**: understanding one end-to-end path required moving from Python ingestion code in `dg_projects/data_loading/...` to Dagster lakehouse definitions and then into the dbt project under `src/ol_dbt`.
- **Asset-to-warehouse mapping**: the repository makes it clear that Dagster, dbt, Airbyte, dlt, Glue, and Superset are all involved, but the exact operational chain is split across several directories and docs.
- **Blind blast radius**: a single missed handoff between Python orchestration and dbt assets would produce the wrong downstream impact model.

### Cartographer Priorities
These pain points inform why the **Brownfield Cartographer** must prioritize:
1. **Automated cross-stack DAG visualization** so a new engineer does not need multiple directories open to understand one pipeline.
2. **Unified Python, SQL, and config lineage** so ingestion, transformation, and serving can be seen together.
3. **Blast-radius analysis** so downstream impact is computed rather than remembered.
