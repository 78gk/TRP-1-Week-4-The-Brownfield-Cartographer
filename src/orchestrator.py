import os
import time
import json
import tempfile
import subprocess
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

from src.graph.knowledge_graph import KnowledgeGraph
from src.agents.surveyor import SurveyorAgent
from src.agents.hydrologist import HydrologistAgent
from src.agents.archivist import ArchivistAgent

try:
    from src.agents.semanticist import SemanticistAgent
    from src.utils.token_budget import ContextWindowBudget
    SEMANTICIST_AVAILABLE = True
except ImportError:
    SEMANTICIST_AVAILABLE = False

logger = logging.getLogger(__name__)

class CartographyOrchestrator:
    """Orchestrates the sequential execution of Cartographer agents."""

    def __init__(self, repo_path: str, output_dir: str = ".cartography", 
                 skip_semantics: bool = False, incremental: bool = False):
        self._is_temp_dir = False
        
        # Git Repo handling
        if repo_path.startswith("http") or repo_path.startswith("git@"):
            logger.info(f"Cloning remote repository {repo_path}...")
            self.repo_path = self._clone_repo(repo_path)
            self._is_temp_dir = True
        else:
            self.repo_path = os.path.abspath(repo_path)
            if not os.path.isdir(self.repo_path):
                 raise ValueError(f"Target repository path does not exist: {self.repo_path}")
                 
        self.output_dir = output_dir
        self.skip_semantics = skip_semantics
        self.incremental = incremental
        
        self.knowledge_graph = KnowledgeGraph()
        self.knowledge_graph.metadata.setdefault("agent_action_trace", [])
        
        # Ensure output dict
        out_path = Path(self.repo_path) / self.output_dir
        out_path.mkdir(parents=True, exist_ok=True)
        
        # Setup basic tracking details
        self.results_summary: Dict[str, Any] = {}

    def run(self) -> Dict[str, Any]:
        """Execute the full agent pipeline sequentially."""
        start_time = time.time()
        logger.info(f"Starting Cartographer Pipeline. Target: {self.repo_path}")
        
        changed_files = None
        if self.incremental:
             changed_files = self._get_changed_files()
             if changed_files is not None:
                  logger.info(f"Incremental mode active: analyzing {len(changed_files)} changed files.")
                  self._load_previous_graph_state()
             else:
                  logger.warning("Incremental mode requested, but no prior run metadata found. Falling back to full analysis.")

        analysis_scope = None
        if changed_files is not None:
            analysis_scope = [
                p for p in changed_files
                if Path(self.repo_path, p).exists()
            ]
                  
        # 1. Pipeline execution flags
        run_semanticist = SEMANTICIST_AVAILABLE and not self.skip_semantics
        
        # 2. Sequential execution
        
        # --- Surveyor Agent ---
        try:
            logger.info("Executing Phase 1: Surveyor Agent...")
            self._record_agent_action("Surveyor", "started", "static_analysis", "static")
            # Current Surveyor API takes a KnowledgeGraph and exposes analyze(repo_path).
            surveyor = SurveyorAgent(self.knowledge_graph)
            surveyor_summary = surveyor.analyze(self.repo_path, target_files=analysis_scope)
            self.results_summary["surveyor"] = surveyor_summary
            self._record_agent_action("Surveyor", "completed", "static_analysis", "static", details=surveyor_summary)
        except Exception as e:
            logger.error(f"Surveyor Agent failed: {e}")
            self.results_summary["surveyor"] = {"error": str(e)}
            self._record_agent_action("Surveyor", "failed", "static_analysis", "static", confidence="high", details={"error": str(e)})

        # --- Hydrologist Agent ---
        try:
            logger.info("Executing Phase 2: Hydrologist Agent...")
            self._record_agent_action("Hydrologist", "started", "sql_parsing", "static")
            # Current Hydrologist API takes a KnowledgeGraph and exposes analyze(repo_path).
            hydro = HydrologistAgent(self.knowledge_graph)
            hydrologist_summary = hydro.analyze(self.repo_path, target_files=analysis_scope)
            self.results_summary["hydrologist"] = hydrologist_summary
            self._record_agent_action("Hydrologist", "completed", "sql_parsing", "static", details=hydrologist_summary)
        except Exception as e:
            logger.error(f"Hydrologist Agent failed: {e}")
            self.results_summary["hydrologist"] = {"error": str(e)}
            self._record_agent_action("Hydrologist", "failed", "sql_parsing", "static", confidence="high", details={"error": str(e)})

        # --- Semanticist Agent ---
        if run_semanticist:
             try:
                 logger.info("Executing Phase 3: Semanticist Agent...")
                 self._record_agent_action("Semanticist", "started", "llm_inference", "llm")
                 semanticist = SemanticistAgent(
                     self.repo_path, 
                     self.knowledge_graph,
                     budget=ContextWindowBudget(total_budget_usd=1.0)
                 )
                 self.knowledge_graph = semanticist.run()
                 self.results_summary["semanticist"] = semanticist.get_summary()
                 self._record_agent_action("Semanticist", "completed", "llm_inference", "llm", details=self.results_summary["semanticist"])
             except Exception as e:
                 logger.error(f"Semanticist Agent failed: {e}")
                 self.results_summary["semanticist"] = {"error": str(e)}
                 self._record_agent_action("Semanticist", "failed", "llm_inference", "llm", confidence="medium", details={"error": str(e)})
        else:
             logger.info("Skipping Semanticist validation phase.")
             self.results_summary["semanticist"] = "Skipped"
             self._record_agent_action("Semanticist", "skipped", "system", "static", confidence="high")

        # --- Archivist Agent ---
        try:
            logger.info("Executing Phase 4: Archivist Agent...")
            self._record_agent_action("Archivist", "started", "system", "static")
            archivist = ArchivistAgent(self.repo_path, self.knowledge_graph, output_dir=self.output_dir)
            archivist.run()
            self.results_summary["archivist"] = "Artifacts generated successfully"
            self._record_agent_action("Archivist", "completed", "system", "static")
        except Exception as e:
            logger.error(f"Archivist Agent failed: {e}")
            self.results_summary["archivist"] = {"error": str(e)}
            self._record_agent_action("Archivist", "failed", "system", "static", details={"error": str(e)})
            
        # 3. Finalization
        try:
            self._serialize_results()
            self._save_run_metadata()
        except Exception as e:
            logger.error(f"Error saving pipeline outputs: {e}")
            
        elapsed = time.time() - start_time
        logger.info(f"Pipeline complete in {elapsed:.2f} seconds.")
        
        self.results_summary["execution_time_seconds"] = elapsed
        
        return self.results_summary

    def _clone_repo(self, url: str) -> str:
        """Clone an external git repository for analysis."""
        try:
            temp_dir = tempfile.mkdtemp(prefix="cartographer_")
            logger.info(f"Running git clone {url} into {temp_dir}")
            
            result = subprocess.run(
                ["git", "clone", url, temp_dir],
                capture_output=True,
                text=True,
                check=True
            )
            return temp_dir
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to clone repository '{url}'. Git error: {e.stderr}")

    def _get_changed_files(self) -> Optional[List[str]]:
        """Fetch files changed since the commit recorded in the last run."""
        meta_file = Path(self.repo_path) / self.output_dir / ".last_run.json"
        
        if not meta_file.exists():
            return None
            
        try:
            with open(meta_file, 'r') as f:
                meta = json.load(f)
                
            last_commit = meta.get("commit_hash")
            if not last_commit:
                return None
                
            # Use git dir explicit context
            result = subprocess.run(
                ["git", "-C", self.repo_path, "diff", "--name-only", f"{last_commit}..HEAD"],
                capture_output=True,
                text=True,
                check=True
            )
            
            output = result.stdout.strip()
            if not output:
                 return []
            return output.split("\n")
            
        except subprocess.CalledProcessError as e:
             logger.warning(f"Git diff failed for incremental update: {e.stderr}. Triggering full run.")
             return None
        except Exception as e:
             logger.warning(f"Failed to read historical metadata for incremental check: {e}")
             return None

    def _load_previous_graph_state(self) -> None:
        """Load prior run graph artifacts so incremental updates can patch changed files only."""
        out = Path(self.repo_path) / self.output_dir
        module_graph_path = out / "module_graph.json"
        lineage_graph_path = out / "lineage_graph.json"
        try:
            if module_graph_path.exists() and hasattr(self.knowledge_graph, "deserialize_module_graph"):
                self.knowledge_graph.deserialize_module_graph(module_graph_path)
            if lineage_graph_path.exists() and hasattr(self.knowledge_graph, "deserialize_lineage_graph"):
                self.knowledge_graph.deserialize_lineage_graph(lineage_graph_path)
        except Exception as e:
            logger.warning(f"Could not preload previous graph state for incremental analysis: {e}")

    def _save_run_metadata(self) -> None:
        """Cache the current HEAD and timestamp metadata."""
        meta_file = Path(self.repo_path) / self.output_dir / ".last_run.json"
        
        commit_hash = "unknown"
        try:
            result = subprocess.run(
                 ["git", "-C", self.repo_path, "rev-parse", "HEAD"],
                 capture_output=True,
                 text=True,
                 check=True
            )
            commit_hash = result.stdout.strip()
        except Exception as e:
            logger.warning("Could not determine git HEAD commit hash.")
            
        meta = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "commit_hash": commit_hash,
            "repo_path": self.repo_path,
            "files_analyzed": len(self.knowledge_graph.get_all_nodes()),
            "incremental": self.incremental
        }
        
        with open(meta_file, "w") as f:
            json.dump(meta, f, indent=2)

    def _serialize_results(self) -> None:
        """Call internal serializers iteratively safely ensuring JSON representations written."""
        out = Path(self.repo_path) / self.output_dir
        
        if hasattr(self.knowledge_graph, "serialize_module_graph"):
            loc = out / "module_graph.json"
            self.knowledge_graph.serialize_module_graph(str(loc))
            sz = loc.stat().st_size if loc.exists() else 0
            logger.info(f"Serialized module graph -> {loc} ({sz} bytes)")
            
        if hasattr(self.knowledge_graph, "serialize_lineage_graph"):
            loc = out / "lineage_graph.json"
            self.knowledge_graph.serialize_lineage_graph(str(loc))
            sz = loc.stat().st_size if loc.exists() else 0
            logger.info(f"Serialized lineage graph -> {loc} ({sz} bytes)")

    def _record_agent_action(
        self,
        agent: str,
        action: str,
        evidence_source: str,
        analysis_method: str,
        confidence: str = "high",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.knowledge_graph.metadata.setdefault("agent_action_trace", []).append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent": agent,
            "action": action,
            "evidence_source": evidence_source,
            "analysis_method": analysis_method,
            "confidence": confidence,
            "details": details or {},
        })

    def get_results_summary(self) -> Dict[str, Any]:
        """Provide finalized execution tracking summary dictionary."""
        return self.results_summary

