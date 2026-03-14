import logging
import math
import re
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple
import networkx as nx

from src.graph.knowledge_graph import KnowledgeGraph
from src.models.nodes import ModuleNode, DatasetNode

try:
    from src.utils.llm_client import LLMClient
    from src.utils.token_budget import ModelTier
except ImportError:
    LLMClient = None
    ModelTier = None

try:
    from langgraph.graph import StateGraph
    LANGGRAPH_AVAILABLE = True
except ImportError:
    LANGGRAPH_AVAILABLE = False


logger = logging.getLogger(__name__)

@dataclass
class ToolResult:
    """Standardized response from any Navigator analysis tool."""
    tool_name: str
    query: str
    result: Any
    evidence_files: List[str]
    evidence_ranges: List[str]
    evidence_source: str  # "static_analysis" | "graph_traversal" | "llm_inference" | "vector_search"
    confidence: str  # "high" | "medium" | "low"
    explanation: str

class NavigatorAgent:
    """
    A query agent that allows interactive interrogation of the knowledge graph. 
    It uses either LangGraph (if available) or a heuristic agent loop with four 
    specific tools to provide evidence-cited responses.
    """
    
    def __init__(self, knowledge_graph: KnowledgeGraph, llm_client: Optional[Any] = None):
        self.knowledge_graph = knowledge_graph
        self.llm_client = llm_client

    # --- Tool 1: find_implementation ---
    
    def find_implementation(self, concept: str) -> ToolResult:
        """Find where a concept is implemented in the codebase."""
        concept_lower = concept.lower()
        query_vec = self._text_to_vector(concept_lower)
        matches = []
        
        for node in self.knowledge_graph.get_all_nodes():
            if not isinstance(node, ModuleNode):
                continue
                
            score = 0
            match_reasons = []
            
            # Exact path match is strongest signal
            if concept_lower in node.path.lower():
                score += 10
                match_reasons.append(f"Path matched '{concept}'")

            # Simple semantic similarity over path/classes/functions/purpose text.
            candidate_text = " ".join([
                node.path,
                " ".join(node.classes or []),
                " ".join(node.public_functions or []),
                node.purpose_statement or "",
            ]).lower()
            semantic_score = self._cosine_similarity(query_vec, self._text_to_vector(candidate_text))
            if semantic_score > 0.0:
                score += semantic_score * 8.0
                match_reasons.append(f"Semantic similarity={semantic_score:.2f}")
                
            # Class name match
            if node.classes and any(concept_lower in c.lower() for c in node.classes):
                score += 5
                match_reasons.append(f"Class name matched '{concept}'")
                
            # Function name match
            if node.public_functions and any(concept_lower in f.lower() for f in node.public_functions):
                score += 3
                match_reasons.append(f"Function name matched '{concept}'")
                
            # Semantic purpose statement match
            if node.purpose_statement and concept_lower in node.purpose_statement.lower():
                score += 2
                match_reasons.append("Purpose statement reference")
                
            if score > 0:
                matches.append({
                    "node": node,
                    "score": score,
                    "reasons": match_reasons,
                    "range": "L1"
                })
                
        # Sort by relevance
        matches.sort(key=lambda x: x["score"], reverse=True)
        top_matches = matches[:5]
        
        files_cited = [m["node"].path for m in top_matches]
        ranges_cited = [f"{m['node'].path}:{m.get('range', 'L1')}" for m in top_matches]
        
        if top_matches:
            explanation = "Found implementations ranked by relevance:\n"
            for m in top_matches:
                node = m["node"]
                reasons = ", ".join(m["reasons"])
                purpose = node.purpose_statement or "No semantic purpose generated."
                explanation += f"\n- {node.path} [Score: {m['score']}] ({reasons})\n  Purpose: {purpose}\n"
        else:
            explanation = f"Could not find any modules implementing '{concept}'"
            
        return ToolResult(
            tool_name="find_implementation",
            query=concept,
            result=top_matches,
            evidence_files=files_cited,
            evidence_ranges=ranges_cited,
            evidence_source="vector_search",
            confidence="high" if top_matches and top_matches[0]["score"] >= 5 else "low",
            explanation=explanation
        )

    # --- Tool 2: trace_lineage ---

    def trace_lineage(self, dataset_name: str, direction: str = "upstream") -> ToolResult:
        """Trace the data lineage for a given dataset."""
        if not hasattr(self.knowledge_graph, "lineage_graph") or not self.knowledge_graph.lineage_graph:
            return ToolResult(
                tool_name="trace_lineage", query=dataset_name, result=[], evidence_files=[],
                evidence_ranges=[],
                evidence_source="graph_traversal", confidence="low",
                explanation="No lineage graph available in the knowledge graph dataset."
            )
            
        G = self.knowledge_graph.lineage_graph
        try:
             # Find actual node name matching dataset (case-insensitive substring if exact fails)
             target_node = dataset_name
             if target_node not in G.nodes():
                 possible = [n for n in G.nodes() if dataset_name.lower() in str(n).lower()]
                 if possible:
                     target_node = possible[0]
                 else:
                     return ToolResult(
                         tool_name="trace_lineage", query=dataset_name, result=[], evidence_files=[],
                         evidence_ranges=[],
                         evidence_source="graph_traversal", confidence="high",
                         explanation=f"Dataset '{dataset_name}' not found in the lineage graph."
                     )
                     
             lineage = []
             evidence = []
             evidence_ranges = []
             
             if direction == "upstream":
                 ancestors = nx.ancestors(G, target_node)
                 subgraph = G.subgraph(list(ancestors) + [target_node])
                 path_edges = list(nx.edge_bfs(subgraph, target_node, orientation='reverse'))
                 
                 explanation = f"Upstream lineage for '{target_node}':\n"
                 for src, tgt, data in path_edges:
                     file_ref = G.edges[src, tgt].get('source_file', 'unknown')
                     line_range = G.edges[src, tgt].get('line_range') or G.edges[src, tgt].get('line_number')
                     trans_type = G.edges[src, tgt].get('transformation_type', 'derived')
                     lineage.append((src, tgt, file_ref))
                     evidence.append(file_ref)
                     if file_ref != 'unknown' and line_range is not None:
                         if isinstance(line_range, (list, tuple)) and len(line_range) == 2:
                             evidence_ranges.append(f"{file_ref}:L{line_range[0]}-L{line_range[1]}")
                         else:
                             evidence_ranges.append(f"{file_ref}:L{line_range}")
                     explanation += f"- {src} -> {tgt} (via {trans_type} in {file_ref})\n"
                     
             else: # downstream
                 descendants = nx.descendants(G, target_node)
                 subgraph = G.subgraph(list(descendants) + [target_node])
                 path_edges = list(nx.edge_bfs(subgraph, target_node))
                 
                 explanation = f"Downstream lineage from '{target_node}':\n"
                 for src, tgt, data in path_edges:
                     file_ref = G.edges[src, tgt].get('source_file', 'unknown')
                     line_range = G.edges[src, tgt].get('line_range') or G.edges[src, tgt].get('line_number')
                     trans_type = G.edges[src, tgt].get('transformation_type', 'derived')
                     lineage.append((src, tgt, file_ref))
                     evidence.append(file_ref)
                     if file_ref != 'unknown' and line_range is not None:
                         if isinstance(line_range, (list, tuple)) and len(line_range) == 2:
                             evidence_ranges.append(f"{file_ref}:L{line_range[0]}-L{line_range[1]}")
                         else:
                             evidence_ranges.append(f"{file_ref}:L{line_range}")
                     explanation += f"- {src} -> {tgt} (via {trans_type} in {file_ref})\n"
                     
             if not lineage:
                 explanation += "No dependencies found in this direction."
                 
             return ToolResult(
                 tool_name="trace_lineage",
                 query=f"{dataset_name} ({direction})",
                 result=lineage,
                 evidence_files=list(set([f for f in evidence if f != "unknown"])),
                 evidence_ranges=sorted(set(evidence_ranges))[:10],
                 evidence_source="graph_traversal",
                 confidence="high",
                 explanation=explanation
             )
        except Exception as e:
            logger.error(f"Error tracing lineage: {e}")
            return ToolResult(
                tool_name="trace_lineage", query=dataset_name, result=str(e), evidence_files=[],
                evidence_ranges=[],
                evidence_source="graph_traversal", confidence="low", explanation=f"Traversal error: {e}"
            )

    # --- Tool 3: blast_radius ---

    def blast_radius(self, module_path: str) -> ToolResult:
        """Find everything that would break if the given module changed."""
        
        # 1. Structural dependents via module graph imports
        affected_modules = []
        G_mod = self.knowledge_graph.module_graph
        target_path = module_path
        
        # Fuzzy match path if exact fails
        if target_path not in G_mod.nodes():
             possible = [n for n in G_mod.nodes() if target_path.lower() in str(n).lower()]
             if possible: target_path = possible[0]
             
        if target_path in G_mod.nodes():
             # Find dependents (modules that import this one -> edges point TOWARDS this module conceptually? Or away?
             # Assuming standard: importer -> imported. So we need predecessors
             try:
                 # Check graph edge direction assumption
                 descendants = nx.descendants(G_mod, target_path) # Assuming node -> importer 
                 if not list(descendants): # If empty, maybe graph is inverted importer -> node
                      descendants = nx.ancestors(G_mod, target_path) 
                 
                 for node in descendants:
                     dist = nx.shortest_path_length(G_mod, target_path, node) if nx.has_path(G_mod, target_path, node) else 1
                     affected_modules.append({"path": node, "distance": dist})
             except nx.NetworkXError:
                 pass
                 
        # 2. Lineage Graph Dependents (datasets produced by this module)
        affected_datasets = set()
        if hasattr(self.knowledge_graph, "lineage_graph") and self.knowledge_graph.lineage_graph:
             G_lin = self.knowledge_graph.lineage_graph
             for u, v, data in G_lin.edges(data=True):
                 if data.get('source_file') == target_path:
                      affected_datasets.add(v) # the dataset being written
                      # and everything downstream
                      try:
                          affected_datasets.update(nx.descendants(G_lin, v))
                      except:
                          pass

        # Sort modules by distance
        affected_modules.sort(key=lambda x: x["distance"])
        
        explanation = f"Blast Radius for '{target_path}':\n"
        explanation += f"- Affected Modules: {len(affected_modules)}\n"
        for m in affected_modules[:5]:
             explanation += f"  - [Dist {m['distance']}] {m['path']}\n"
        if len(affected_modules) > 5:
             explanation += f"  - ... ({len(affected_modules) - 5} more)\n"
             
        explanation += f"- Affected Datasets: {len(affected_datasets)}\n"
        for d in list(affected_datasets)[:5]:
             explanation += f"  - {d}\n"
             
        evidence = [m["path"] for m in affected_modules]
        evidence_ranges = [f"{m['path']}:L1" for m in affected_modules[:10]]
        
        return ToolResult(
             tool_name="blast_radius",
             query=module_path,
             result={"modules": affected_modules, "datasets": list(affected_datasets)},
             evidence_files=evidence[:10],
               evidence_ranges=evidence_ranges,
             evidence_source="graph_traversal",
             confidence="high",
             explanation=explanation
        )

    # --- Tool 4: explain_module ---

    def explain_module(self, path: str) -> ToolResult:
        """Explain what a specific module does using structural data and purpose statements."""
        target_path = path
        matched_node = None
        
        for node in self.knowledge_graph.get_all_nodes():
            if isinstance(node, ModuleNode):
                 if target_path.lower() in node.path.lower():
                     matched_node = node
                     break
                     
        if not matched_node:
             return ToolResult(
                 tool_name="explain_module", query=path, result=None, evidence_files=[],
                 evidence_ranges=[],
                 evidence_source="static_analysis", confidence="high",
                 explanation=f"Module matching '{path}' not found in the parsed knowledge graph."
             )
             
        explanation = f"Module profile: {matched_node.path}\n\n"
        
        evidence_src = "static_analysis"
        if matched_node.purpose_statement:
             explanation += f"**Purpose**: {matched_node.purpose_statement}\n"
             evidence_src = "llm_inference"
        else:
             explanation += "**Purpose**: No semantic purpose statement available.\n"
             
        explanation += f"- **Language**: {matched_node.language}\n"
        explanation += f"- **Domain**: {matched_node.domain_cluster or 'Unknown'}\n"
        explanation += f"- **Complexity**: {matched_node.complexity_score} (LOC)\n"
        explanation += f"- **Dead Code Candidate**: {'Yes' if matched_node.is_dead_code_candidate else 'No'}\n\n"
        
        if matched_node.public_functions:
             explanation += "**Public API Functions**:\n"
             for f in matched_node.public_functions[:5]:
                 explanation += f"- {f}\n"
                 
        if matched_node.classes:
             explanation += "**Classes**:\n"
             for c in matched_node.classes:
                 explanation += f"- {c}\n"
                 
        if matched_node.imports:
             explanation += "**Key Dependencies**:\n"
             for m in matched_node.imports[:5]:
                 explanation += f"- {m}\n"
                 
        return ToolResult(
            tool_name="explain_module", query=path, result=matched_node, evidence_files=[matched_node.path],
            evidence_ranges=[f"{matched_node.path}:L1"],
            evidence_source=evidence_src, confidence="high", explanation=explanation
        )

    # --- Routing & Execution ---

    def query(self, user_query: str) -> ToolResult:
        """Route the user query to the appropriate tool (with LLM or heuristic fallback)."""
        logger.info(f"Navigator received query: '{user_query}'")
        
        q = user_query.lower()
        
        # --- LangGraph LLM Execution (If supported & configured) ---
        if LANGGRAPH_AVAILABLE and self.llm_client and self.llm_client.is_available():
             lg_result = self._try_langgraph_agent(user_query)
             if lg_result: 
                 return lg_result
                 
        # --- Heuristic Keyword Routing Fallback ---
        subject = self._extract_subject(q)
        
        # Basic multi-step chaining: ask for impacted modules and then explain the top hit.
        if any(w in q for w in ["then explain", "and explain"]):
            base_query = re.sub(r"\s+(and|then)\s+explain.*$", "", q).strip()
            base_subject = self._extract_subject(base_query)
            base = self.blast_radius(base_subject)
            modules = base.result.get("modules", []) if isinstance(base.result, dict) else []
            if modules:
                followup = self.explain_module(modules[0]["path"])
                return ToolResult(
                    tool_name="blast_radius+explain_module",
                    query=user_query,
                    result={"blast_radius": base.result, "explain_module": followup.result},
                    evidence_files=list(dict.fromkeys(base.evidence_files + followup.evidence_files)),
                    evidence_ranges=list(dict.fromkeys(base.evidence_ranges + followup.evidence_ranges)),
                    evidence_source="graph_traversal",
                    confidence="high",
                    explanation=base.explanation + "\n\nFollow-up explanation:\n" + followup.explanation,
                )
            # If no downstream modules are found, still explain the directly referenced target.
            followup = self.explain_module(base_subject)
            return ToolResult(
                tool_name="blast_radius+explain_module",
                query=user_query,
                result={"blast_radius": base.result, "explain_module": followup.result},
                evidence_files=list(dict.fromkeys(base.evidence_files + followup.evidence_files)),
                evidence_ranges=list(dict.fromkeys(base.evidence_ranges + followup.evidence_ranges)),
                evidence_source="graph_traversal",
                confidence=base.confidence,
                explanation=base.explanation + "\n\nFollow-up explanation:\n" + followup.explanation,
            )

        if any(w in q for w in ["lineage", "upstream", "downstream", "produces", "consumes", "feeds", "parent", "child"]):
             direction = "downstream" if "downstream" in q or "produces" in q or "feeds" in q else "upstream"
             return self.trace_lineage(subject, direction)
             
        elif any(w in q for w in ["blast radius", "what breaks", "impact", "change", "affects", "downstream"]):
             return self.blast_radius(subject)
             
        elif any(w in q for w in ["explain", "what does", "describe", "purpose", "how does"]):
             return self.explain_module(subject)
             
        elif any(w in q for w in ["where is", "find", "implementation", "which file", "how to"]):
             return self.find_implementation(subject)
             
        return self.find_implementation(subject) # default

    def _text_to_vector(self, text: str) -> Dict[str, float]:
        tokens = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", text.lower())
        if not tokens:
            return {}
        total = float(len(tokens))
        vec: Dict[str, float] = {}
        for t in tokens:
            vec[t] = vec.get(t, 0.0) + 1.0 / total
        return vec

    def _cosine_similarity(self, a: Dict[str, float], b: Dict[str, float]) -> float:
        if not a or not b:
            return 0.0
        dot = 0.0
        for k, va in a.items():
            dot += va * b.get(k, 0.0)
        norm_a = math.sqrt(sum(v * v for v in a.values()))
        norm_b = math.sqrt(sum(v * v for v in b.values()))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def _extract_subject(self, query: str) -> str:
        """Naive NLP extraction to find the target of the query."""
        q = query.lower()
        path_match = re.search(r"([\w\-/\.]+\.(?:py|sql|ya?ml|json|md))", q)
        if path_match:
            return path_match.group(1)

        stopwords = ["where", "is", "the", "find", "implementation", "of", "what", "does", "explain", "describe", 
                     "lineage", "for", "blast", "radius", "breaks", "if", "i", "change", "upstream", "downstream", "module", "file", "table", "dataset", "and", "then"]
                     
        words = q.replace("?", "").replace("'", "").replace('"', '').split()
        target_words = [w for w in words if w not in stopwords]
        
        if not target_words:
            # Fallback if everything was stripped
            target_words = words[-2:] if len(words) > 1 else words
            
        return "_".join(target_words)

    def _try_langgraph_agent(self, user_query: str) -> Optional[ToolResult]:
         """Placeholder for LangGraph implementations (Requires extensive tool mapping not fully viable in constraint space)."""
         # In a full build, this would define a StateGraph with nodes executing the 4 tools.
         # For this specific requirement, we return None to let the core heuristic handler process reliably.
         return None

    def _format_result(self, result: ToolResult) -> str:
        """Format a ToolResult for console output."""
        
        confidence_emoji = {
              "high": "[HIGH]", "medium": "[MED]", "low": "[LOW]"
        }
        
        src_map = {
              "static_analysis": "Static AST",
              "graph_traversal": "Graph Math",
              "llm_inference": "Semantic AI",
              "vector_search": "Vector Search"
        }
        
        out = f"\nTool: {result.tool_name}\n"
        out += f"Results:\n{result.explanation}\n"
        out += f"\nEvidence: {', '.join(result.evidence_files[:3])}{'...' if len(result.evidence_files)>3 else ''}\n"
        if result.evidence_ranges:
            out += f"Line ranges: {', '.join(result.evidence_ranges[:3])}{'...' if len(result.evidence_ranges)>3 else ''}\n"
        out += f"  [{src_map.get(result.evidence_source, result.evidence_source)}, {confidence_emoji.get(result.confidence, '')} {result.confidence} confidence]\n"
        return out

    def interactive_mode(self) -> None:
        """Run an interactive REPL query session."""
        print("\nBrownfield Cartographer - Navigator")
        print("Type your query (or 'quit' to exit):\n")
        
        while True:
            try:
                user_input = input("\n> ")
                if user_input.strip().lower() in ["quit", "exit", "q"]:
                    print("Exiting Navigator.")
                    break
                    
                if not user_input.strip():
                    continue
                    
                result = self.query(user_input)
                print(self._format_result(result))
                
            except KeyboardInterrupt:
                print("\nExiting Navigator.")
                break
            except EOFError:
                print("\nExiting Navigator.")
                break
            except Exception as e:
                logger.error(f"REPL Error: {e}")
                print(f"\n\u274c Error processing query: {e}")
