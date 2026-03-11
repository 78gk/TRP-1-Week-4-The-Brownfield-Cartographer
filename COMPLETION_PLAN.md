## Completion Plan for Final Submission

The final deadline is **Sunday March 15, 03:00 UTC** (approx. 3 days from interim). The following roadmap outlines the execution plan to achieve the final system vision.

### Critical Path (Must Complete)

**Day 1 (Friday March 13): Semanticist Agent**
1.  **Cost Control**: Build a `ContextWindowBudget` class for rigorous LLM token and cost tracking.
2.  **Bulk Analysis**: Implement `generate_purpose_statement()` using Gemini Flash to generate business-context summaries for all modules.
3.  **Audit**: Implement documentation drift detection by comparing generated purpose statements against existing source docstrings.
4.  **Clustering**: Implement `cluster_into_domains()` using text embeddings and k-means to identify logical system boundaries.
    - *Dependency*: Knowledge Graph must be fully populated by the Surveyor.
    - *Technical Risk*: Clustering quality depends on embedding quality; requires prompt tuning for consistent business-language summaries.

**Day 2 (Saturday March 14): Archivist Agent + Scaled Validation**
5.  **Blueprint Generation**: Implement `generate_CODEBASE.md` with sections for Architecture Overview, architectural "hubs" (PageRank), Data I/O, Technical Debt, and High-Velocity files.
6.  **Onboarding Tool**: Implement `onboarding_brief.md` generation that automatically answers the FDE Day-One Questions with direct evidence citations.
7.  **Audit Log**: Implement `cartography_trace.jsonl` for a detailed audit trail of all agent actions and analytical steps.
8.  **Platform Validation**: Run the full 4-agent pipeline on a larger target codebase (e.g., `Apache Airflow` example DAGs or `mitodl/ol-data-platform`).
    - *Dependency*: Archivist requires Semanticist data; must run after Day 1 completes.

**Day 3 (Sunday March 15 morning): Navigator + Demo + Final Polish**
9.  **Interactive Assistant**: Build the **Navigator** LangGraph agent with tools for implementation lookup, lineage tracing, blast radius computation, and module explanation.
10. **Final Integration**: Update the `CartographerOrchestrator` to sequence all 4 specialized agents.
11. **Query Interface**: Add a `query` subcommand to the CLI for interactive Navigator sessions.
12. **Evidence**: Record a 6-minute demo video following the project's Demo Protocol.
13. **Final Report**: Write the comprehensive final PDF report consolidate all findings.

---

### Stretch Goals
- **Incremental Mode**: Implement re-analysis of only changed files via `git diff` for speed.
- **Self-Audit**: Run the Cartographer on its own codebase to identify internal complexity.
- **Multi-Target Analysis**: Validate against a third data platform codebase.

---

### Technical Risks & Mitigations
- **LLM Prompt Precision**: Summaries might focus on code implementation rather than business function. *Mitigation*: Iterative prompt engineering and few-shot examples for the Semanticist.
- **Domain Clustering Stability**: K-means results can be unpredictable at high dimensions. *Mitigation*: Fall back to rule-based directory-to-domain mapping if embeddings fail to produce stable clusters.
- **Navigator Integration Overhead**: LangGraph can introduce debugging complexity. *Mitigation*: Build Navigator tools as standalone Python functions first; if the graph wiring becomes a bottleneck, use a direct CLI query interface as the fallback.

---

### Fallback Strategy
If time runs short, the priority order is:
1.  **Semanticist** (Highest value-add over structural analysis).
2.  **Archivist** (Key deliverable for living documentation).
3.  **Second Codebase Validation** (Proves system robustness).
4.  **Simplified Navigator** (Manual tool access via CLI instead of a full LLM agent).
5.  **Demo Video** (Ensure the core delivery is documented).

*Stretch goals (Incremental mode, self-audit) are explicitly deprioritized.*
