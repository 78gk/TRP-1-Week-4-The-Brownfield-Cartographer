## Accuracy Observations

This document records what the interim outputs get right, what they get wrong, and why those errors are happening.

Validation note: these accuracy observations are based on the actual interim prototype run against `dbt-labs/jaffle-shop`. The manual reconnaissance target used to eliminate rubric qualification risk is now `mitodl/ol-data-platform`, which is a separate report section and not the current automated validation target.

## 1. Module Graph Assessment

### Correct detections
- The exported `module_graph.json` is now a clean structural view rather than a mixed graph.
- The current artifact does not include dataset nodes or lineage-style `consumes` edges in the structural export.

### Inaccuracies
- On dbt-heavy targets, the structural graph is sparse because the most important dependencies are model-lineage relationships rather than Python import relationships.

### Likely cause
- The current design intentionally keeps the structural graph and lineage graph separate, so non-import dependencies appear in the lineage artifact instead.

## 2. Lineage Graph Assessment

### Correct detections
- The generated lineage output contains source datasets such as `ecom.raw_customers` and `ecom.raw_orders`, which aligns with the manually observed seed-to-stage ingestion path.
- The graph contains dataset nodes like `stg_orders`, which matches the manually identified critical staging layer.
- The system now emits explicit dbt reference edges such as `stg_orders -> orders` and `orders -> customers`, which makes the main lineage chain directly inspectable.

### Inaccuracies
- Many lineage edges point to `JINJA_PLACEHOLDER` rather than the real upstream dbt model or source.
- That means the current system does not yet recover the full `ref()`-based lineage chain at table level for dbt-templated SQL.
- Source file metadata in GitHub-URL validation runs currently reflects the temporary clone path rather than a normalized repo-relative path.

### Likely cause
- In `src/analyzers/sql_lineage.py`, Jinja expressions are stripped before `sqlglot` parsing and replaced with `JINJA_PLACEHOLDER`.
- dbt refs are extracted separately and now recover key model-to-model edges, but the SQL-AST path still produces placeholder noise for macro-heavy statements.

## 3. Comparison Against Manual Validation On `jaffle_shop`

### Correct interim detections
1. The system identifies core business datasets and staging models that manual exploration also identified as important, including `stg_orders`, `orders`, and `customers`.
2. The system recognizes raw warehouse sources like `ecom.raw_customers` and `ecom.raw_orders`, which matches the documented ingestion path.

### Known interim misses
1. dbt-templated SQL often collapses to `JINJA_PLACEHOLDER`, obscuring some upstream dependency detail on the SQL-AST path.
2. The lineage graph still mixes multiple evidence types together, so deduplication and confidence labels would improve readability.
3. Source-file metadata in cloned-repo runs is not yet normalized back to repo-relative paths.

## 4. Interim Conclusion

The interim output is now materially useful on a real dbt repository and strong enough to validate the architecture and implementation strategy. It is still not production-grade lineage quality on macro-heavy SQL, but the core dependency chains are now visible in the generated artifact.
