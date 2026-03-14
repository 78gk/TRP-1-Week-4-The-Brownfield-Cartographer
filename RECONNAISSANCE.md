## 1. Reconnaissance: Manual vs. Automated Analysis

### Manual Day-One Analysis (Ground Truth)

I manually explored the jaffle_shop repository (`https://github.com/dbt-labs/jaffle_shop`) — a dbt project with SQL models, YAML config, and seed CSV data.

#### Q1: Primary Data Ingestion Path
**Manual Finding**: Raw data enters the system via seed CSV files in the `seeds/` directory: `raw_customers.csv`, `raw_orders.csv`, and `raw_payments.csv`. These are loaded by the `dbt seed` command into the data warehouse as source tables. The staging layer (`models/staging/stg_customers.sql`, `models/staging/stg_orders.sql`, `models/staging/stg_payments.sql`) then references these via `{{ source('jaffle_shop', 'raw_orders') }}` macros to clean and standardize the raw data.

**System-Generated Finding**: The Cartographer's Hydrologist Agent and `onboarding_brief.md` correctly identified the seed files (`raw_customers.csv`, `raw_orders.csv`, `raw_payments.csv`) as the data sources (entry points with in-degree=0). The SQL analyzer combined with the `schema.yml` configuration parsing correctly inferred the `source()` bindings mapping to the physical seeds.

**Verdict**: ✅ Correct. The Hydrologist engine accurately determined the true upstream pipeline boundaries extending beyond `.sql` logic into the `.csv` physical files.

#### Q2: 3-5 Most Critical Output Datasets
**Manual Finding**: The two mart-level models are the critical outputs:
1. `models/customers.sql` — produces the `customers` table: a customer-level summary with order counts, first/last order dates, and lifetime value.
2. `models/orders.sql` — produces the `orders` table: an order-level fact table with payment amounts joined from the payments staging model.

These are the only models materialized as tables (vs. views) in the default configuration and act as terminal nodes.

**System-Generated Finding**: The Cartographer's graph metrics (`get_lineage_sinks`) successfully flagged `customers` and `orders` as the sole datasets with an out-degree of 0 (nothing consumes them). The Semanticist's prompt correctly synthesized this information, providing both datasets as the final output artifacts. 

**Verdict**: ✅ Correct. The lineage extraction algorithms mathematically proved these paths are endpoints, removing the guesswork needed to manually evaluate materialization definitions.

#### Q3: Blast Radius of Most Critical Module
**Manual Finding**: `models/staging/stg_orders.sql` is the most critical staging model because:
- `models/orders.sql` refs it directly (`{{ ref('stg_orders') }}`).
- `models/customers.sql` joins with orders data, creating an indirect dependency.
- If `stg_orders` breaks: both final mart models (orders AND customers) fail to build.
- This means ALL downstream consumers of customer and order data are affected.

**System-Generated Finding**: Triggering the Navigator's `blast_radius()` tool on `models/staging/stg_orders.sql` successfully traversed the `import_graph` and `lineage_graph` (via distance calculations). It outputted `models/orders.sql` and `models/customers.sql` as directly impacted downstream dependencies, explicitly mapping the cross-file SQL model connections.

**Verdict**: ✅ Correct. The recursive BFS tree correctly spanned dependencies out towards the graph edges.

#### Q4: Business Logic Concentration
**Manual Finding**: Business logic is concentrated in the mart-level models:
- `models/customers.sql` (40 lines) — contains the most complex business logic: customer lifetime value calculation, aggregation of order history, and join across all three staging models.
- `models/orders.sql` (30 lines) — contains payment amount pivoting logic (credit card, coupon, bank transfer, gift card amounts).
- Staging models are thin wrappers (renaming columns, casting types) with minimal business logic.

**System-Generated Finding**: The Semanticist LLM's purpose extraction properly isolated analytical logic versus staging translation logic. The K-means clustering rule-based fallback partitioned the items cleanly into the `transformation` (mart logic) and `staging` domains utilizing both folder hierarchies (`models/staging` vs `models`) and semantic complexity markers.

**Verdict**: ✅ Correct. The system accurately pinpointed logical centers based on density metrics without needing a manual audit of every SQL block.

#### Q5: Recent Change Velocity
**Manual Finding**: This is a canonical example project that is relatively stable. Most recent commits focus on README updates and configuration changes rather than model logic changes. The `models/customers.sql` and `models/orders.sql` files have the most historical commits as they are the core of the project.

**System-Generated Finding**: The Surveyor's `git log --follow` parsing yielded blank or minimal results mapping largely to `dbt_project.yml` initialization commits rather than robust model velocity logic since the repository was analyzed as a fresh local clone without pulling full historical depth beyond the top commit chain.

**Verdict**: ⚠️ Partially Correct. While the system's output reflects the state of the *local `.git` clone provided to it*, it lacked the historical depth to truly identify "hot" files in an operational context unless the user specifically fetched origin histories prior to running Cartographer.

---

### Difficulty Analysis
What was hardest to figure out manually:

1. **Tracing cross-file ref() dependencies**: Each SQL model file contains `{{ ref('other_model') }}` calls. Manually tracing which staging model feeds which mart model required opening 5+ SQL files and mapping `ref()` calls by hand. In a larger dbt project with 200+ models, this would be prohibitively time-consuming. This directly informs why the Cartographer's SQL lineage analyzer (`sql_lineage.py`) is the highest-value component, automatically building edge matrices.

2. **Understanding the source() -> staging -> mart data flow**: The connection between seed CSVs in `seeds/`, the `source()` references in `schema.yml`, the `source()` calls in staging SQL, and the final `ref()` chains to mart models spans multiple file types (CSV, YAML, SQL). No single file shows the complete picture. This cross-language dependency tracing is exactly what the Hydrologist agent automates — binding AST configurations across paradigms into a unified NetworkX DiGraph.

3. **Determining which models are "critical" vs. peripheral**: Without running `dbt docs generate`, there's no built-in way to see the full DAG. Manually determining that `customers.sql` is the most connected node required understanding ALL `ref()` relationships. The Surveyor's PageRank analysis automates this importance ranking out-of-the-box using graph centrality algorithms without relying on framework-native compilation servers.

These pain points directly motivated the Cartographer's architecture: the Hydrologist handles cross-language lineage (`dag_config_parser.py` + `sql_lineage.py`), the SQL lineage analyzer handles `ref()` logic extraction, and the Surveyor's PageRank mathematical model identifies critical nodes autonomously.
