import os
import re
import json
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

from src.graph.knowledge_graph import KnowledgeGraph
from src.models.nodes import ModuleNode
from src.utils.token_budget import ContextWindowBudget, ModelTier
from src.utils.llm_client import LLMClient

logger = logging.getLogger(__name__)

class SemanticistAgent:
    """
    The Semanticist agent uses LLMs to generate semantic understanding that static analysis
    cannot provide: purpose statements, documentation drift detection, domain clustering,
    and Day-One question answering.
    """
    
    def __init__(self, repo_path: str, knowledge_graph: KnowledgeGraph, 
                 budget: Optional[ContextWindowBudget] = None):
        self.repo_path = repo_path
        self.knowledge_graph = knowledge_graph
        self._budget = budget or ContextWindowBudget()
        self._llm_client = LLMClient(budget=self._budget)
        
        self._purpose_statements: Dict[str, str] = {}
        self._drift_flags: List[Dict[str, Any]] = []
        self._domain_clusters: Dict[str, str] = {}
        self._day_one_answers: Dict[str, Any] = {}

    def run(self) -> KnowledgeGraph:
        """Execute the full semanticist pipeline."""
        logger.info("Starting Semanticist Agent analysis...")
        
        if not self._llm_client.is_available():
            logger.warning("LLM Client unavailable. Skipping AI-driven analysis and using rule-based fallbacks where possible.")
            
        modules = [n for n in self.knowledge_graph.get_all_nodes() if isinstance(n, ModuleNode)]
        logger.info(f"Generating purpose statements for {len(modules)} modules...")
        
        # a + b) Generate purpose statements and detect drift
        for idx, module in enumerate(modules):
            if idx > 0 and idx % 10 == 0:
                logger.info(f"Processed {idx}/{len(modules)} modules...")
                
            purpose = self.generate_purpose_statement(module)
            if purpose:
                self._purpose_statements[module.path] = purpose
                module.purpose_statement = purpose
                
                # Check for documentation drift
                drift_info = self.detect_documentation_drift(module, purpose)
                if drift_info:
                    self._drift_flags.append(drift_info)
        
        # c) Cluster modules into domains
        logger.info("Clustering modules into business domains...")
        self._domain_clusters = self.cluster_into_domains()
        
        for module in modules:
            if module.path in self._domain_clusters:
                module.domain_cluster = self._domain_clusters[module.path]
                
        # d) Answer FDE questions
        logger.info("Synthesizing Day-One Questions...")
        self._day_one_answers = self.answer_day_one_questions()

        # Persist key semantic outputs so downstream agents can render them.
        if hasattr(self.knowledge_graph, "metadata"):
            self.knowledge_graph.metadata["drift_flags"] = self._drift_flags
            self.knowledge_graph.metadata["day_one_answers"] = self._day_one_answers
            self.knowledge_graph.metadata["domain_clusters"] = self._domain_clusters
            self.knowledge_graph.metadata["purpose_statements"] = self._purpose_statements
        
        # e & f handled implicitly through graph updates and summary tracking
        summary = self.get_summary()
        logger.info(f"Semanticist Agent complete. Summary: {summary}")
        
        # g) Return updated knowledge graph
        return self.knowledge_graph

    def _read_source_code(self, file_path: str, max_chars: int = 8000) -> Optional[str]:
        """Read file content with encoding fallback, truncated to max_chars."""
        abs_path = os.path.join(self.repo_path, file_path)
        if not os.path.exists(abs_path):
            return None
            
        try:
            with open(abs_path, 'r', encoding='utf-8') as f:
                content = f.read(max_chars)
                return content
        except UnicodeDecodeError:
            try:
                with open(abs_path, 'r', encoding='latin-1') as f:
                    content = f.read(max_chars)
                    return content
            except Exception as e:
                logger.warning(f"Failed to read source file {file_path} with latin-1: {e}")
                return None
        except Exception as e:
            logger.warning(f"Failed to read source file {file_path}: {e}")
            return None

    def _extract_docstring(self, file_path: str) -> Optional[str]:
        """Extract module-level docstring from a Python file."""
        if not file_path.endswith('.py'):
            return None
            
        abs_path = os.path.join(self.repo_path, file_path)
        if not os.path.exists(abs_path):
            return None
            
        try:
            with open(abs_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # Naive match for module docstring at top of file
            match = re.search(r'^\s*(?:"""|\'\'\')([\s\S]*?)(?:"""|\'\'\')', content)
            if match:
                return match.group(1).strip()
            return None
        except Exception:
            return None

    def generate_purpose_statement(self, module_node: ModuleNode) -> Optional[str]:
        """Generate a summarized purpose statement using the LLM based purely on code implementation."""
        source_code = self._read_source_code(module_node.path, max_chars=8000)
        
        if not source_code:
            return None
            
        if not self._llm_client.is_available():
            return "Purpose extraction unavailable (Missing API Key)."
            
        sys_instructions = (
            "You are a senior software architect analyzing code for a new team member's onboarding. "
            "Your task is to explain what this module DOES in business terms, not HOW it's implemented.\n"
            "Focus on the module's role in the broader system. \n"
            "IMPORTANT: Analyze the actual code implementation below. Do NOT rely on or repeat any "
            "docstrings or comments — they may be outdated. Base your analysis solely on what the "
            "code actually does."
        )
        
        prompt = (
            f"Analyze this source code and provide a 2-3 sentence Purpose Statement explaining "
            f"what this module does in the context of a data engineering system.\n\n"
            f"File path: {module_node.path}\n"
            f"Language: {module_node.language}\n"
            f"Imports: {module_node.imports}\n"
            f"Public functions: {module_node.public_functions}\n"
            f"Classes: {module_node.classes}\n\n"
            f"Source code:\n```\n{source_code}\n```\n\n"
            f"Respond with ONLY the purpose statement, no preamble."
        )
        
        result = self._llm_client.generate(
            prompt=prompt,
            tier=ModelTier.BULK,
            system_instruction=sys_instructions,
            task_description=f"Generate purpose for {module_node.path}"
        )
        
        if result:
            result = result.strip()
            logger.debug(f"Purpose generated for {module_node.path} ({len(result)} chars)")
            
        return result

    def detect_documentation_drift(self, module_node: ModuleNode, purpose_statement: str) -> Optional[Dict]:
        """Check for discrepancies between extracted docstring and inferred purpose statement."""
        docstring = self._extract_docstring(module_node.path)
        
        if not docstring:
             return {"module": module_node.path, "drift_type": "missing_documentation", "severity": "info"}
             
        if not self._llm_client.is_available():
             return {"module": module_node.path, "drift_type": "unknown_ai_unavailable", "severity": "info"}
             
        prompt = (
            f"Compare these two descriptions of the same code module:\n\n"
            f"ACTUAL BEHAVIOR (from code analysis): {purpose_statement}\n"
            f"DOCUMENTED BEHAVIOR (from docstring): {docstring}\n\n"
            f"Are they consistent? If not, what specifically contradicts?\n"
            f"Respond in JSON format:\n"
            f"{{\"is_consistent\": true/false, \"drift_severity\": \"none|minor|major|critical\", \"contradiction\": \"description of what contradicts or 'none'\"}}"
        )
        
        result = self._llm_client.generate(
            prompt=prompt,
            tier=ModelTier.BULK,
            task_description=f"Detect docs drift for {module_node.path}"
        )
        
        if not result:
            return {"module": module_node.path, "drift_type": "analysis_failed", "severity": "error"}
            
        try:
             # Extract json block if fenced
             match = re.search(r'```json\s*(.*?)\s*```', result, re.DOTALL)
             if match:
                 parsed = json.loads(match.group(1))
             else:
                 parsed = json.loads(result)
                 
             return {
                 "module": module_node.path,
                 "drift_type": "contradiction" if not parsed.get("is_consistent", True) else "consistent",
                 "severity": parsed.get("drift_severity", "none"),
                 "contradiction": parsed.get("contradiction", "none"),
                 "actual_purpose": purpose_statement,
                 "documented_purpose": docstring[:200] + "..." if len(docstring) > 200 else docstring
             }
        except Exception as e:
             logger.warning(f"Failed to parse LLM drift detection JSON for {module_node.path}: {e}")
             return {"module": module_node.path, "drift_type": "parse_error", "severity": "unknown"}

    def _cluster_rule_based(self) -> Dict[str, str]:
        """Fallback clustering logic based on directory and file patterns."""
        clusters = {}
        for node in self.knowledge_graph.get_all_nodes():
            if not isinstance(node, ModuleNode):
                continue
                
            path = node.path.lower()
            if any(x in path for x in ['/models/', '/transforms/', '/transformations/']):
                domain = "transformation"
            elif any(x in path for x in ['/staging/', 'stg_']):
                domain = "staging"
            elif any(x in path for x in ['/seeds/', '/sources/', '/raw/']):
                domain = "data_ingestion"
            elif '/tests/' in path:
                domain = "testing"
            elif path.endswith('_config.py') or path.endswith('.yml') or path.endswith('.yaml') or '/config/' in path:
                domain = "configuration"
            elif any(x in path for x in ['/dags/', '/pipelines/']):
                domain = "orchestration"
            else:
                domain = "utilities"
                
            clusters[node.path] = domain
        return clusters

    def cluster_into_domains(self) -> Dict[str, str]:
        """Cluster modules into domains using LLM synthesis or rule-based fallback."""
        if not self._llm_client.is_available() or not self._purpose_statements:
            return self._cluster_rule_based()
            
        # APPROACH 1: LLM clustering
        modules_list = "\n".join([f"- {path}: {purpose}" for path, purpose in self._purpose_statements.items()])
        
        # Ensure it fits
        if len(modules_list) > 16000:
            modules_list = modules_list[:16000] + "\n... (truncated)"
            
        prompt = (
            f"Given these module purpose statements from a data engineering codebase, "
            f"cluster them into 5-8 business domains (e.g., 'data_ingestion', 'transformation', "
            f"'data_modeling', 'serving', 'configuration', 'testing', 'monitoring', 'utilities').\n\n"
            f"Modules:\n"
            f"{modules_list}\n\n"
            f"Respond in JSON format:\n"
            f"{{\"clusters\": {{\"module_path\": \"domain_name\", ...}}}}"
        )
        
        result = self._llm_client.generate(
            prompt=prompt,
            tier=ModelTier.SYNTHESIS,
            task_description="Cluster modules into business domains"
        )
        
        if result:
            try:
                match = re.search(r'```json\s*(.*?)\s*```', result, re.DOTALL)
                if match:
                   parsed = json.loads(match.group(1))
                else:
                   parsed = json.loads(result)
                   
                return parsed.get("clusters", self._cluster_rule_based())
            except Exception as e:
                logger.warning(f"Failed to parse LLM clustering JSON: {e}")
                
        return self._cluster_rule_based()

    def answer_day_one_questions(self) -> Dict[str, Any]:
        """Synthesize Day-One Questions spanning structural and semantic insight."""
        if not self._llm_client.is_available():
            # Rule based fallback
            return {
                "questions": [
                    {
                        "question": "What is the primary data ingestion path?",
                        "answer": "Answer unavailable: Requires LLM API configuration.",
                        "evidence_files": [], "evidence_source": "system", "confidence": "low"
                    }
                ]
            }

        # Gather graph context
        top_modules = [] # Surveyor dependency
        if hasattr(self.knowledge_graph, "get_top_modules"):
            top_modules_raw = getattr(self.knowledge_graph, "get_top_modules")(limit=5)
            top_modules = [m.path for m in top_modules_raw]
            
        sources = [] # Hydrologist dependency
        sinks = []
        if hasattr(self.knowledge_graph, "get_lineage_sources"):
            sources = [n.name for n in getattr(self.knowledge_graph, "get_lineage_sources")()]
        if hasattr(self.knowledge_graph, "get_lineage_sinks"):
            sinks = [n.name for n in getattr(self.knowledge_graph, "get_lineage_sinks")()]

        circ_deps = []
        if hasattr(self.knowledge_graph, "get_circular_dependencies"):
           circ_deps = getattr(self.knowledge_graph, "get_circular_dependencies")()
           
        clusters_summary = json.dumps(self._domain_clusters)[:3000]
        purpose_statements_summary = json.dumps(self._purpose_statements)[:5000]

        prompt = (
            f"You are an FDE (Forward-Deployed Engineer) who has just run automated analysis "
            f"on a codebase. Based on the following analysis results, answer each of the Five "
            f"FDE Day-One Questions. Cite specific file paths and evidence for each answer.\n\n"
            f"ANALYSIS RESULTS:\n\n"
            f"Top Modules by Importance (PageRank):\n{top_modules}\n\n"
            f"Data Sources (entry points):\n{sources}\n\n"
            f"Data Sinks (output endpoints):\n{sinks}\n\n"
            f"Module Purpose Statements:\n{purpose_statements_summary}\n\n"
            f"Domain Clusters:\n{clusters_summary}\n\n"
            f"Circular Dependencies:\n{circ_deps}\n\n"
            f"QUESTIONS:\n"
            f"1. What is the primary data ingestion path? (Cite specific files and data sources)\n"
            f"2. What are the 3-5 most critical output datasets/endpoints? (Cite specific tables/files)\n"
            f"3. What is the blast radius if the most critical module fails? (List affected downstream modules)\n"
            f"4. Where is the business logic concentrated vs. distributed? (Reference domain clusters and file locations)\n"
            f"5. What has changed most frequently in the last 90 days? (Reference git velocity data)\n\n"
            f"For each answer, include:\n"
            f"- Specific file paths\n"
            f"- Evidence source (static analysis, SQL parsing, git history, or LLM inference)\n"
            f"- Confidence level (high/medium/low)\n\n"
            f"Respond in JSON format:\n"
            f"{{\"questions\": [\n"
            f"  {{\"question\": \"...\", \"answer\": \"...\", \"evidence_files\": [...], \"evidence_source\": \"...\", \"confidence\": \"high|medium|low\"}},\n"
            f"  ...\n"
            f"]}}"
        )

        result = self._llm_client.generate(
            prompt=prompt,
            tier=ModelTier.SYNTHESIS,
            max_output_tokens=2048,
            task_description="Synthesize FDE Day-One Questions"
        )
        
        if result:
            try:
                match = re.search(r'```json\s*(.*?)\s*```', result, re.DOTALL)
                if match:
                   return json.loads(match.group(1))
                else:
                   return json.loads(result)
            except Exception as e:
                logger.warning(f"Failed to parse LLM Day-One answers JSON: {e}")
                
        return {"questions": []}

    def get_summary(self) -> Dict[str, Any]:
        """Return execution summary statistics."""
        severity_counts = {}
        for flag in self._drift_flags:
            sev = flag.get("severity", "unknown")
            severity_counts[sev] = severity_counts.get(sev, 0) + 1
            
        domain_counts = {}
        for domain in self._domain_clusters.values():
            domain_counts[domain] = domain_counts.get(domain, 0) + 1
            
        return {
            "purpose_statements_generated": len(self._purpose_statements),
            "drift_flags": len(self._drift_flags),
            "drift_flags_by_severity": severity_counts,
            "domain_clusters": domain_counts,
            "day_one_answers_generated": len(self._day_one_answers.get('questions', [])) > 0,
            "llm_budget_summary": self._budget.get_usage_summary() if self._budget else {},
        }
