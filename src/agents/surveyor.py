import logging
import os
from pathlib import Path
from typing import Dict, List, Any, Set, Tuple
import networkx as nx

from src.graph.knowledge_graph import KnowledgeGraph
from src.models.nodes import ModuleNode, FunctionNode, NodeType
from src.models.edges import ImportEdge, EdgeType
from src.analyzers.tree_sitter_analyzer import TreeSitterAnalyzer
from src.analyzers.sql_lineage import SQLLineageAnalyzer
from src.analyzers.dag_config_parser import DAGConfigParser

logger = logging.getLogger(__name__)

class SurveyorAgent:
    """Agent that crawls a codebase and builds a structural knowledge graph."""

    def __init__(self, kg: KnowledgeGraph):
        self.kg = kg
        self.ts_analyzer = TreeSitterAnalyzer()
        self.sql_analyzer = SQLLineageAnalyzer()
        self.config_parser = DAGConfigParser()

    def analyze(self, dir_path: str) -> Dict[str, Any]:
        """Crawl the directory and populate the knowledge graph."""
        root = Path(dir_path)
        
        # 1. Analyze code files
        for file_path in root.rglob("*"):
            if any(p.startswith(".") for p in file_path.parts):
                continue
            if "__pycache__" in file_path.parts:
                continue
            
            if file_path.suffix == ".py":
                self._analyze_python_file(file_path)
            elif file_path.suffix == ".sql":
                self._analyze_sql_file(file_path)

        # 2. Analyze configs (dbt, Airflow metadata)
        config_result = self.config_parser.analyze_directory(dir_path)
        # For now, we'll focus on the summary metrics requested in validation
        
        # 3. Calculate metrics
        summary = self._generate_summary()
        return summary

    def _analyze_python_file(self, file_path: Path):
        """Extract nodes and edges from a Python file."""
        rel_path = str(file_path)
        
        # Create/Add Module node
        module_node = ModuleNode(
            path=rel_path,
            language="python"
        )
        self.kg.add_module_node(module_node)
        
        # Run TreeSitter analysis
        try:
            result = self.ts_analyzer.analyze_file(str(file_path))
            
            # Add imports
            for imp in result.imports:
                # Basic target module matching (simplified for now)
                self.kg.add_import_edge(ImportEdge(
                    source=rel_path,
                    target=imp.module_path,
                    is_relative=imp.is_relative
                ))
            
            # Add functions
            for func in result.functions:
                # We could add FunctionNodes here if needed
                pass
                
        except Exception as e:
            logger.error(f"Error analyzing {rel_path}: {e}")

    def _analyze_sql_file(self, file_path: Path):
        """Extract nodes and edges from a SQL file."""
        rel_path = str(file_path)
        
        # Create Module node
        module_node = ModuleNode(
            path=rel_path,
            language="sql"
        )
        self.kg.add_module_node(module_node)
        
        # Run SQL analysis
        try:
            lineage = self.sql_analyzer.analyze_file(str(file_path))
            # Population logic could follow here for DatasetNodes etc.
        except Exception as e:
            logger.error(f"Error analyzing {rel_path}: {e}")

    def _generate_summary(self) -> Dict[str, Any]:
        """Generate high-level summary and importance metrics."""
        summary = self.kg.summary()
        
        # Calculate PageRank on the module import graph
        # Filter edges for IMPORTS
        import_subgraph = nx.DiGraph()
        
        nodes = self.kg._graph.nodes(data=True)
        for u, v, d in self.kg._graph.edges(data=True):
            if d.get("edge_type") == EdgeType.IMPORTS.value:
                import_subgraph.add_edge(u, v)
        
        # Add all module nodes even if no edges
        for node_id, data in nodes:
            if data.get("node_type") == NodeType.MODULE.value:
                import_subgraph.add_node(node_id)
        
        if import_subgraph.number_of_nodes() > 0:
            try:
                pagerank = nx.pagerank(import_subgraph)
            except Exception:
                # Fallback if graph is weird
                pagerank = {n: 0.0 for n in import_subgraph.nodes()}
        else:
            pagerank = {}
            
        top_pagerank = sorted(pagerank.items(), key=lambda x: x[1], reverse=True)
        
        return {
            "total_modules": summary.get("module_nodes", 0),
            "total_import_edges": summary.get("edge_type_counts", {}).get(EdgeType.IMPORTS.value, 0),
            "top_pagerank_modules": top_pagerank
        }
