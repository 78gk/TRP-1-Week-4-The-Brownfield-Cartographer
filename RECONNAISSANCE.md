# RECONNAISSANCE.md: jaffle_shop Codebase Audit

This report documents the manual reconnaissance of the `jaffle_shop` dbt repository, answering critical architectural and data flow questions.

## 1. Primary Data Ingestion Path
The primary ingestion path is **Seed-to-Stage**.
- **Source**: Raw data enters the system via static CSV files located in the `seeds/` directory:
    - [seeds/raw_customers.csv](https://github.com/dbt-labs/jaffle-shop/blob/main/seeds/raw_customers.csv)
    - [seeds/raw_orders.csv](https://github.com/dbt-labs/jaffle-shop/blob/main/seeds/raw_orders.csv)
    - [seeds/raw_payments.csv](https://github.com/dbt-labs/jaffle-shop/blob/main/seeds/raw_payments.csv)
- **Mechanism**: Data is loaded into the warehouse via the `dbt seed` command. It is then ingested into the modeling layer by **staging models** using the `{{ source() }}` macro. 
- **Key Pattern**: `models/staging/stg_orders.sql` references the seed via `{{ source('jaffle_shop', 'raw_orders') }}`, effectively serving as the first "logical" ingestion point.

## 2. Most Critical Output Datasets
The 3 most critical "Marts" or final datasets are:
1.  **[models/customers.sql](https://github.com/dbt-labs/jaffle-shop/blob/main/models/customers.sql)**: The primary dimension for Customer 360 analysis, aggregating orders and lifetime value.
2.  **[models/orders.sql](https://github.com/dbt-labs/jaffle-shop/blob/main/models/orders.sql)**: The central fact table for transaction lifecycle analysis, joining order data with payment statuses.
3.  **[models/staging/stg_payments.sql](https://github.com/dbt-labs/jaffle-shop/blob/main/models/staging/stg_payments.sql)**: While a staging model, it is the sole source of "truth" for payment success/failure, which flows into both major marts.

## 3. Blast Radius Analysis: `stg_orders.sql` failure
If [models/staging/stg_orders.sql](https://github.com/dbt-labs/jaffle-shop/blob/main/models/staging/stg_orders.sql) fails to build:
1.  **Direct Impact**: `models/orders.sql` will fail because it contains `from {{ ref('stg_orders') }}`.
2.  **Downstream Impact**: Since `models/customers.sql` references `{{ ref('orders') }}`, it will also fail to calculate customer-level order aggregates.
3.  **Total Result**: The entire business-facing "Mart" layer is effectively taken offline by a single staging failure.

## 4. Business Logic: Concentrated vs. Distributed
- **Distributed (Transformation)**: Format cleaning and renaming are distributed across the `models/staging/` directory (e.g., `stg_customers.sql` renames `id` to `customer_id`).
- **Concentrated (Calculation)**: Complex business logic (Current vs. Lifetime value) is concentrated in the root `models/` folder. Specifically, **`models/customers.sql`** contains the complex CTE logic for joining orders and payments to define the "Customer" entity.

## 5. Most Frequent Changes (Last 90 Days)
Based on git history:
- **[models/schema.yml](https://github.com/dbt-labs/jaffle-shop/blob/main/models/schema.yml)**: Changes most frequently as new tests and documentation are added for every model tweak.
- **[dbt_project.yml](https://github.com/dbt-labs/jaffle-shop/blob/main/dbt_project.yml)**: Frequent updates for versioning and package management.
- **[models/staging/stg_payments.sql](https://github.com/dbt-labs/jaffle-shop/blob/main/models/staging/stg_payments.sql)**: Often modified to handle new payment methods or naming conventions.

---

## DIFFICULTY ANALYSIS

### Manual Pain Points
- **Tracing `ref()` Chains**: Manually figuring out which staging model feeds which mart model required opening 5+ SQL files simultaneously to build a mental map of the DAG. For example, to understand `customers.sql`, I had to trace back through `orders.sql`, then through `stg_orders.sql` and `stg_payments.sql`.
- **Source-to-Table Mapping**: Connecting the `{{ source() }}` calls in `models/staging/` to the actual CSVs in `seeds/` was non-obvious without cross-referencing `models/sources.yml`.
- **Blind Blast Radius**: Predicting that a change in `stg_orders.sql` would break `customers.sql` requires perfect knowledge of the entire project topology; a single missed `ref()` makes manual impact analysis unreliable.

### Cartographer Priorities
These pain points inform why the **Brownfield Cartographer** must prioritize:
1.  **Automated DAG Visualization**: Eliminating the "5-file open" requirement by showing immediate `ref()` neighbors.
2.  **Unified SQL/YAML View**: Mapping the `sources.yml` definitions directly to the code that consumes them.
3.  **Explosive Lineage**: A dedicated `blast_radius` command that recursively follows `ref()` calls to show exactly which downstream files are at risk.
