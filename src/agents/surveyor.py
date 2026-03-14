import logging
import os
from pathlib import Path
from typing import Dict, List, Any, Set, Tuple, Optional
from datetime import datetime, timedelta
import networkx as nx
from git import Repo

from src.graph.knowledge_graph import KnowledgeGraph
from src.models.nodes import ModuleNode, FunctionNode, NodeType
from src.models.edges import ImportEdge, EdgeType
from src.analyzers.tree_sitter_analyzer import TreeSitterAnalyzer
from src.analyzers.sql_lineage import SQLLineageAnalyzer
from src.analyzers.dag_config_parser import DAGConfigParser

logger = logging.getLogger(__name__)

class SurveyorAgent:
    """Agent 1: The Surveyor - Static Structure Analyst.
    
    Crawl codebase using tree-sitter, build structural graph, and
    compute architectural metrics (PageRank, Git Velocity, Dead Code).
    """

    def __init__(self, kg: KnowledgeGraph):
        self.kg = kg
        self.ts_analyzer = TreeSitterAnalyzer()
        self.sql_analyzer = SQLLineageAnalyzer()
        self.config_parser = DAGConfigParser()

    def analyze(self, dir_path: str, target_files: Optional[List[str]] = None) -> Dict[str, Any]:
        """Crawl the directory and populate the knowledge graph."""
        root = Path(dir_path).resolve()
        scoped_files: Optional[Set[str]] = None
        if target_files is not None:
            scoped_files = {
                str(Path(p).as_posix()).lstrip("./")
                for p in target_files
                if Path(p).suffix.lower() in (".py", ".sql", ".yaml", ".yml")
            }
        
        # 1. Initialize Git Repo if available
        repo = None
        try:
            repo = Repo(dir_path, search_parent_directories=True)
            logger.info("Surveyor: Git repository detected.")
        except Exception:
            logger.warning("Surveyor: No Git repository found. Velocity analysis will be skipped.")

        # 2. Crawl and analyze files
        for file_path in root.rglob("*"):
            if any(p.startswith(".") for p in file_path.parts):
                continue
            if "__pycache__" in file_path.parts:
                continue
            
            ext = file_path.suffix.lower()
            if ext in (".py", ".sql", ".yaml", ".yml"):
                rel_norm = str(file_path.relative_to(root)).replace('\\', '/')
                if scoped_files is not None and rel_norm not in scoped_files:
                    continue
                self._analyze_file(file_path, root, repo)

        # 3. Analyze configs (dbt, Airflow metadata)
        self.config_parser.analyze_directory(str(root))
        
        # 4. Perform Advanced Graph Analytics
        analytics = self._perform_structural_analytics()
        
        # 5. Generate Summary
        summary = self._generate_summary(analytics)
        return summary

    def _analyze_file(self, file_path: Path, root_path: Path, repo: Optional[Repo] = None):
        """Extract nodes and metadata from a file."""
        rel_path = str(file_path.relative_to(root_path)).replace('\\', '/')
        ext = file_path.suffix.lower()
        
        language = "unknown"
        if ext == ".py": language = "python"
        elif ext == ".sql": language = "sql"
        elif ext in (".yaml", ".yml"): language = "yaml"

        # Basic metrics
        try:
            with open(file_path, "r", encoding="utf-8", errors='replace') as f:
                lines = f.readlines()
                loc = len(lines)
                comment_count = sum(1 for l in lines if l.strip().startswith(('#', '--', '/*')))
                comment_ratio = comment_count / loc if loc > 0 else 0
        except Exception:
            loc, comment_ratio = 0, 0

        # Git Velocity
        velocity = 0
        last_modified = None
        if repo:
            try:
                # 30 day window
                since = datetime.now() - timedelta(days=30)
                commits = list(repo.iter_commits(paths=str(file_path), since=since))
                velocity = len(commits)
                if commits:
                    last_modified = datetime.fromtimestamp(commits[0].committed_date)
            except Exception as e:
                logger.debug(f"Could not extract git velocity for {rel_path}: {e}")

        # Create/Add Module node
        module_node = ModuleNode(
            path=rel_path,
            language=language,
            lines_of_code=loc,
            comment_ratio=comment_ratio,
            change_velocity_30d=velocity,
            last_modified=last_modified
        )
        
        # Run TreeSitter analysis
        try:
            result = self.ts_analyzer.analyze_file(str(file_path), repo_root=str(root_path))
            module_node.public_functions = [f.name for f in result.functions if not f.name.startswith('_')]
            module_node.classes = [c.name for c in result.classes]
            module_node.imports = [i.resolved_path or i.module_path for i in result.imports]
            module_node.decorators = sorted({decorator for f in result.functions for decorator in f.decorators})
            module_node.complexity_score = float(
                len(result.functions) + len(result.classes) + len(result.imports)
            )
            
            # Add node to KG
            self.kg.add_module_node(module_node)
            
            # Add imports to KG
            for imp in result.imports:
                target = imp.resolved_path or imp.module_path
                self.kg.add_import_edge(ImportEdge(
                    source=rel_path,
                    target=target,
                    import_names=imp.symbols,
                    source_file=rel_path,
                ))
            
            # Add functions as nodes
            for func in result.functions:
                qualified_name = f"{rel_path}:{func.name}"
                fn_node = FunctionNode(
                    qualified_name=qualified_name,
                    parent_module=rel_path,
                    signature=func.signature,
                    line_number=func.line_number,
                    is_public_api=not func.name.startswith('_'),
                    decorators=func.decorators
                )
                self.kg.add_function_node(fn_node)
                
        except Exception as e:
            logger.error(f"Error analyzing {rel_path}: {e}")
            self.kg.add_module_node(module_node)

    def _perform_structural_analytics(self) -> Dict[str, Any]:
        """Compute advanced metrics on the structural graph."""
        import_subgraph = nx.DiGraph()
        
        edges = self.kg.get_edges_by_type(EdgeType.IMPORTS.value)
        for u, v in edges:
            import_subgraph.add_edge(u, v)
        
        # Ensure all module nodes are in the subgraph
        module_nodes = self.kg.get_module_nodes()
        for path in module_nodes:
            import_subgraph.add_node(path)
            
        # 1. PageRank (Hub Discovery)
        pagerank = {}
        if import_subgraph.number_of_nodes() > 0:
            try:
                pagerank = nx.pagerank(import_subgraph, weight='import_count')
            except Exception:
                pagerank = {n: 0.0 for n in import_subgraph.nodes()}

        for node_id, score in pagerank.items():
            if node_id in module_nodes:
                self.kg.update_node_attributes(node_id, pagerank_score=score)

        # 2. Circular Dependencies (SCC)
        circular_components = [list(c) for c in nx.strongly_connected_components(import_subgraph) if len(c) > 1]
        
        # 3. Dead Code Detection
        # Candidates have out-degree (importing others) but in-degree is 0 (no one imports them)
        # and they are not entry points or scripts.
        dead_candidates = []
        for node in import_subgraph.nodes():
            if import_subgraph.in_degree(node) == 0 and not self._is_entrypoint_module(node):
                # Flag in metadata
                if node in module_nodes:
                    self.kg.update_node_attributes(node, is_dead_code_candidate=True)
                    dead_candidates.append(node)

        imported_symbols: Set[str] = set()
        for _, _, edge_data in self.kg.graph.edges(data=True):
            if edge_data.get("edge_type") == EdgeType.IMPORTS.value:
                imported_symbols.update(edge_data.get("import_names", []))

        function_dead_candidates = []
        for function_id, function_node in self.kg.get_function_nodes().items():
            function_name = function_id.rsplit(':', 1)[-1]
            if (
                function_node.is_public_api
                and function_name not in imported_symbols
                and function_name not in {'main'}
            ):
                self.kg.update_node_attributes(function_id, is_dead_code_candidate=True)
                function_dead_candidates.append(function_id)

        # 4. High-Velocity Files (80/20 rule)
        velocities = [(n, m.change_velocity_30d) for n, m in module_nodes.items()]
        velocities.sort(key=lambda x: x[1], reverse=True)
        top_20_count = max(1, len(velocities) // 5)
        high_velocity_files = [v[0] for v in velocities[:top_20_count] if v[1] > 0]

        return {
            "pagerank": pagerank,
            "circular_dependencies": circular_components,
            "dead_code_candidates": dead_candidates,
            "dead_function_candidates": function_dead_candidates,
            "high_velocity_files": high_velocity_files
        }

    def _generate_summary(self, analytics: Dict[str, Any]) -> Dict[str, Any]:
        """Generate high-level summary and importance metrics."""
        summary = self.kg.summary()
        
        top_pagerank = sorted(analytics["pagerank"].items(), key=lambda x: x[1], reverse=True)[:5]
        
        return {
            "total_modules": summary.get("module_nodes", 0),
            "total_import_edges": summary.get("edge_type_counts", {}).get(EdgeType.IMPORTS.value, 0),
            "top_architectural_hubs": top_pagerank,
            "circular_dependency_count": len(analytics["circular_dependencies"]),
            "dead_code_candidate_count": len(analytics["dead_code_candidates"]) + len(analytics.get("dead_function_candidates", [])),
            "high_velocity_files": analytics["high_velocity_files"]
        }

    def _is_entrypoint_module(self, module_path: str) -> bool:
        entrypoints = ('__main__.py', 'cli.py', 'main.py')
        normalized = module_path.replace('\\', '/')
        return normalized.endswith(entrypoints)
