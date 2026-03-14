import os
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

from src.graph.knowledge_graph import KnowledgeGraph
from src.models.nodes import ModuleNode, DatasetNode

logger = logging.getLogger(__name__)

class ArchivistAgent:
    """
    Produces and maintains the system's output artifacts as living documents. 
    It consumes outputs from Surveyor, Hydrologist, and Semanticist via the 
    shared KnowledgeGraph and generates structured files.
    """
    
    def __init__(self, repo_path: str, knowledge_graph: KnowledgeGraph, output_dir: str = ".cartography"):
        self.repo_path = repo_path
        self.knowledge_graph = knowledge_graph
        self.output_dir = output_dir
        self._trace_entries: List[Dict] = []
        
        # Ensure output directory exists
        path = Path(self.repo_path) / self.output_dir
        path.mkdir(parents=True, exist_ok=True)

    def run(self) -> None:
        """Full archivist pipeline execution."""
        logger.info("Starting Archivist Agent execution...")
        
        self.log_trace(
            agent_name="Archivist", 
            action="started_execution", 
            evidence_source="system"
        )
        
        # Ensure outputs are generated
        try:
            self.generate_codebase_md()
            self.generate_onboarding_brief()
            self.write_trace_log()
            
            logger.info(f"Artifacts successfully generated in {self.output_dir}/")
        except Exception as e:
             logger.error(f"Failed to generate archivist artifacts: {e}")
             self.log_trace("Archivist", "execution_failed", "system", "high", {"error": str(e)})

    def log_trace(self, agent_name: str, action: str, evidence_source: str, 
                  confidence: str = "high", details: Optional[Dict] = None) -> None:
        """Append an audit trace entry for actions taken by the intelligence system."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent": agent_name,
            "action": action,
            "evidence_source": evidence_source,
            "confidence": confidence,
            "details": details or {}
        }
        self._trace_entries.append(entry)

    def write_trace_log(self) -> None:
        """Write all trace entries to the audit JSONL log."""
        log_path = Path(self.repo_path) / self.output_dir / "cartography_trace.jsonl"
        try:
            with open(log_path, "w", encoding="utf-8") as f:
                for entry in self._trace_entries:
                    f.write(json.dumps(entry) + "\n")
                    
            self.log_trace("Archivist", "wrote_trace_log", "system")
        except Exception as e:
            logger.error(f"Failed to write trace log: {e}")

    # Query Helper Methods targeting the Knowledge Graph

    def _get_top_modules_by_pagerank(self, n: int = 10) -> List[Dict]:
        """Fetch highest PageRank modules from Graph."""
        if hasattr(self.knowledge_graph, "get_top_modules"):
            top_nodes = self.knowledge_graph.get_top_modules(limit=n)
        else:
            top_nodes = [] # fallback
            
        results = []
        for rank, node in enumerate(top_nodes, start=1):
             if isinstance(node, ModuleNode):
                  results.append({
                      "rank": rank,
                      "path": node.path,
                      "pagerank": getattr(self.knowledge_graph, "get_node_pagerank", lambda x: 0.0)(node.path),
                      "purpose": node.purpose_statement or "Unknown",
                      "domain": node.domain_cluster or "Unknown"
                  })
        return results

    def _get_high_velocity_files(self, n: int = 10) -> List[Dict]:
        """Fetch modules with highest 30-day change velocity."""
        modules = [n for n in self.knowledge_graph.get_all_nodes() if isinstance(n, ModuleNode)]
        sorted_modules = sorted(modules, key=lambda x: x.change_velocity_30d, reverse=True)[:n]
        
        results = []
        for module in sorted_modules:
             if module.change_velocity_30d > 0:
                 results.append({
                     "path": module.path,
                     "velocity": module.change_velocity_30d,
                     "pagerank": getattr(self.knowledge_graph, "get_node_pagerank", lambda x: 0.0)(module.path),
                     "domain": module.domain_cluster or "Unknown"
                 })
        return results

    def _get_sources_and_sinks(self) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
        """Fetch lineage entry and exit points."""
        sources = []
        sinks = []
        
        if hasattr(self.knowledge_graph, "get_lineage_sources"):
            for node in self.knowledge_graph.get_lineage_sources():
                if isinstance(node, DatasetNode):
                     sources.append({"name": node.name, "storage_type": node.storage_type})
                     
        if hasattr(self.knowledge_graph, "get_lineage_sinks"):
            for node in self.knowledge_graph.get_lineage_sinks():
                if isinstance(node, DatasetNode):
                     sinks.append({"name": node.name, "storage_type": node.storage_type})
                     
        return sources, sinks

    def _get_domain_summary(self) -> Dict[str, List[str]]:
        """Group module paths by their domain cluster."""
        domains = {}
        for node in self.knowledge_graph.get_all_nodes():
            if isinstance(node, ModuleNode):
                 domain = node.domain_cluster or "uncategorized"
                 domains.setdefault(domain, []).append(node.path)
        return domains

    def _get_dead_code(self) -> List[str]:
        """Get candidates flagged as dead code."""
        return [node.path for node in self.knowledge_graph.get_all_nodes() 
                if isinstance(node, ModuleNode) and node.is_dead_code_candidate]

    def _get_circular_deps(self) -> List[List[str]]:
        """Fetch circular dependencies."""
        if hasattr(self.knowledge_graph, "find_strongly_connected_components"):
            return [component for component in self.knowledge_graph.find_strongly_connected_components() if len(component) > 1]
        return []

    def _get_drift_flags(self) -> List[Dict]:
        """Fetch semantic drift flags (assuming passed through the context metadata of the graph)."""
        if hasattr(self.knowledge_graph, "metadata") and "drift_flags" in self.knowledge_graph.metadata:
            return self.knowledge_graph.metadata.get("drift_flags", [])
        return []

    def _get_day_one_answers(self) -> Dict[str, Any]:
         """Fetch Day One Answers from Graph Metadata."""
         if hasattr(self.knowledge_graph, "metadata") and "day_one_answers" in self.knowledge_graph.metadata:
            return self.knowledge_graph.metadata.get("day_one_answers", {})
         return {}


    # Artifact Generation Methods
    
    def generate_codebase_md(self) -> str:
        """Generate the living context file structured for injection into AI agents."""
        
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        
        # Fetch required data
        top_modules = self._get_top_modules_by_pagerank(10)
        sources, sinks = self._get_sources_and_sinks()
        dead_code = self._get_dead_code()
        circles = self._get_circular_deps()
        velocity = self._get_high_velocity_files(10)
        domains = self._get_domain_summary()
        drift_flags = self._get_drift_flags()
        
        # Build structure
        lines = [
            f"# CODEBASE.md - Living Architectural Context",
            f"# Auto-generated by The Brownfield Cartographer",
            f"# Generated: {timestamp}",
            f"# Target: {self.repo_path}\n",
            
            f"## Architecture Overview",
            f"This codebase consists of {len(self.knowledge_graph.get_all_nodes())} components organized into {len(domains)} core domains.",
            f"It sources data from {len(sources)} entry points and produces {len(sinks)} outputs.\n",
            
            f"## Critical Path",
            f"The following modules have the highest architectural impact (by PageRank centrality):\n",
            f"| Rank | Module | PageRank | Purpose | Domain |",
            f"|------|--------|----------|---------|--------|"
        ]
        
        for mod in top_modules:
             lines.append(f"| {mod['rank']} | `{mod['path']}` | {mod['pagerank']:.4f} | {mod['purpose'][:60]}... | {mod['domain']} |")
             
        if not top_modules:
             lines.append("| - | No modules indexed | - | - | - |")
             
        lines.append("\n## Data Sources & Sinks\n")
        lines.append("### Sources (Data Entry Points)")
        for src in sources:
             lines.append(f"- **{src['name']}** ({src['storage_type']})")
        if not sources:
             lines.append("- No tracked sources identified.")
             
        lines.append("\n### Sinks (Data Output Points)")
        for sink in sinks:
             lines.append(f"- **{sink['name']}** ({sink['storage_type']})")
        if not sinks:
             lines.append("- No tracked sinks identified.")
             
        lines.append("\n## Data Lineage Summary")
        lines.append(f"Tracked data flow from {len(sources)} inputs to {len(sinks)} outputs through graph representations.\n")

        lines.append("## Known Debt\n")
        lines.append("### Circular Dependencies")
        for cycle in circles:
            if len(cycle) <= 6:
                lines.append(f"- [CIRCULAR] Circular: {' <-> '.join(cycle)} <-> {cycle[0]}")
            else:
                 lines.append(f"- [CIRCULAR] Large Circular Component: {len(cycle)} modules centered around {cycle[0]}")
        if not circles:
             lines.append("- No circular imports detected.")
             
        lines.append("\n### Documentation Drift")
        for flag in drift_flags:
             lines.append(f"- [DRIFT] `{flag.get('module', 'unknown')}`: {flag.get('severity', 'unknown')} - {flag.get('contradiction', 'drift')}")
        if not drift_flags:
             lines.append("- No specific contradictions detected.")
             
        lines.append("\n### Dead Code Candidates")
        for dc in dead_code:
             lines.append(f"- [DEAD] `{dc}` - No internal importers detected")
        if not dead_code:
             lines.append("- No clear dead code detected.")

        lines.append("\n## High-Velocity Files (Most Frequently Changed)")
        lines.append("Files with the highest change frequency in the last 30 days:\n")
        lines.append("| File | Changes (30d) | PageRank | Domain |")
        lines.append("|------|---------------|----------|--------|")
        for v in velocity:
             lines.append(f"| `{v['path']}` | {v['velocity']} | {v['pagerank']:.4f} | {v['domain']} |")
        if not velocity:
             lines.append("| No git history | - | - | - |")

        lines.append("\n## Module Purpose Index")
        for node in self.knowledge_graph.get_all_nodes():
             if isinstance(node, ModuleNode):
                 lines.append(f"\n### `{node.path}`")
                 lines.append(f"- **Domain**: {node.domain_cluster or 'uncategorized'}")
                 lines.append(f"- **Purpose**: {node.purpose_statement or 'No purpose generated.'}")
                 lines.append(f"- **Language**: {node.language}")
                 lines.append(f"- **Complexity**: {node.complexity_score}")
                 lines.append(f"- **Key imports**: {', '.join(node.imports[:5]) if node.imports else 'None'}")

        lines.append("\n## Domain Architecture Map")
        for domain_name, module_paths in domains.items():
             lines.append(f"\n### {domain_name} ({len(module_paths)} modules)")
             for path in module_paths:
                 lines.append(f"- `{path}`")

        content = "\n".join(lines)
        
        codebase_path = Path(self.repo_path) / self.output_dir / "CODEBASE.md"
        with open(codebase_path, "w", encoding="utf-8") as f:
            f.write(content)
            
        self.log_trace("Archivist", "generated_codebase_md", "static_analysis", "high")
        return content

    def generate_onboarding_brief(self) -> str:
        """Generate the FDE Day-One Brief answering five core questions with evidence."""
        
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        answers_data = self._get_day_one_answers()
        questions = answers_data.get("questions", [])
        
        # Lookup helper
        def get_q_data(idx_match: str) -> Dict:
            for q in questions:
                 if getattr(q, 'get', lambda x: "")("question", "").startswith(idx_match):
                      return q
            return {
                "answer": "Data unavailable. Run Semanticist Agent with LLM capability.",
                "evidence_source": "system",
                "evidence_files": [],
                "confidence": "low"
            }
            
        q1 = get_q_data("1.")
        q2 = get_q_data("2.")
        q3 = get_q_data("3.")
        q4 = get_q_data("4.")
        q5 = get_q_data("5.")
        
        domains = self._get_domain_summary()
        sources, sinks = self._get_sources_and_sinks()

        lines = [
            f"# FDE Day-One Onboarding Brief",
            f"# Auto-generated by The Brownfield Cartographer",
            f"# Generated: {timestamp}",
            f"# Target: {self.repo_path}\n",
            
            f"## Executive Summary",
            f"This architecture consists of a primary set of **{len(domains)} domains**, "
            f"ingesting data across **{len(sources)} sources** to service **{len(sinks)} primary sinks**.\n",
            
            f"## Day-One Questions & Answers\n",
            
            f"### Q1: What is the primary data ingestion path?",
            f"**Answer**: {(q1.get('answer', 'Data Unavailable.'))}\n",
            f"**Evidence**:",
            f"- Source: {q1.get('evidence_source', 'unknown')}",
            f"- Files: {', '.join(q1.get('evidence_files', [])) or 'None cited'}",
            f"- Confidence: {q1.get('confidence', 'low')}\n",
            
            f"### Q2: What are the 3-5 most critical output datasets/endpoints?",
            f"**Answer**: {(q2.get('answer', 'Data Unavailable.'))}\n",
            f"**Evidence**:",
            f"- Source: {q2.get('evidence_source', 'sql_parsing')}",
            f"- Files: {', '.join(q2.get('evidence_files', [])) or 'None cited'}",
            f"- Confidence: {q2.get('confidence', 'low')}\n",

            f"### Q3: What is the blast radius if the most critical module fails?",
            f"**Answer**: {(q3.get('answer', 'Data Unavailable.'))}\n",
            f"**Evidence**:",
            f"- Source: {q3.get('evidence_source', 'static_analysis')}",
            f"- Files/Paths Impacted: {', '.join(q3.get('evidence_files', [])) or 'None cited'}",
            f"- Confidence: {q3.get('confidence', 'low')}\n",

            f"### Q4: Where is the business logic concentrated vs. distributed?",
            f"**Answer**: {(q4.get('answer', 'Data Unavailable.'))}\n",
            f"**Evidence**:",
            f"- Source: {q4.get('evidence_source', 'llm_inference')}",
            f"- Files: {', '.join(q4.get('evidence_files', [])) or 'None cited'}",
            f"- Confidence: {q4.get('confidence', 'low')}\n",

            f"### Q5: What has changed most frequently in the last 90 days?",
            f"**Answer**: {(q5.get('answer', 'Data Unavailable.'))}\n",
            f"**Evidence**:",
            f"- Source: {q5.get('evidence_source', 'git_history')}",
            f"- Files: {', '.join(q5.get('evidence_files', [])) or 'None cited'}",
            f"- Confidence: {q5.get('confidence', 'low')}\n",

            f"## Quick Reference",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Total modules analyzed | {len([n for n in self.knowledge_graph.get_all_nodes() if isinstance(n, ModuleNode)])} |",
            f"| Languages detected | {list(set([getattr(n, 'language', 'unknown') for n in self.knowledge_graph.get_all_nodes() if isinstance(n, ModuleNode)]))} |",
            f"| Data sources identified | {len(sources)} |",
            f"| Data sinks identified | {len(sinks)} |",
            f"| Circular dependencies | {len(self._get_circular_deps())} |",
            f"| Dead code candidates | {len(self._get_dead_code())} |",
            f"| Documentation drift flags | {len(self._get_drift_flags())} |",
        ]

        content = "\n".join(lines)
        
        brief_path = Path(self.repo_path) / self.output_dir / "onboarding_brief.md"
        with open(brief_path, "w", encoding="utf-8") as f:
            f.write(content)
            
        self.log_trace("Archivist", "generated_onboarding_brief", "llm_inference", "high")
        return content
