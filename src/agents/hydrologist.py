import logging
import re
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple, Any
from collections import deque

import networkx as nx

from src.analyzers.sql_lineage import SQLLineageAnalyzer, SQLLineageResult
from src.analyzers.dag_config_parser import DAGConfigParser, DAGConfigResult
from src.analyzers.tree_sitter_analyzer import TreeSitterAnalyzer, AnalysisResult
from src.graph.knowledge_graph import KnowledgeGraph
from src.models.nodes import DatasetNode, TransformationNode
from src.models.edges import ProducesEdge, ConsumesEdge, ConfiguresEdge

logger = logging.getLogger(__name__)

# Patterns for detecting data operations in Python code
PYTHON_DATA_PATTERNS = {
    'pandas_read': [
        r'pd\.read_csv\s*\(\s*[\'"]([^\'"]+)[\'"]',
        r'pd\.read_sql\s*\(\s*[\'"]([^\'"]+)[\'"]',
        r'pd\.read_excel\s*\(\s*[\'"]([^\'"]+)[\'"]',
        r'pd\.read_parquet\s*\(\s*[\'"]([^\'"]+)[\'"]',
        r'pd\.read_json\s*\(\s*[\'"]([^\'"]+)[\'"]',
        r'pandas\.read_csv\s*\(\s*[\'"]([^\'"]+)[\'"]',
        r'pandas\.read_sql\s*\(\s*[\'"]([^\'"]+)[\'"]',
    ],
    'pandas_write': [
        r'\.to_csv\s*\(\s*[\'"]([^\'"]+)[\'"]',
        r'\.to_sql\s*\(\s*[\'"]([^\'"]+)[\'"]',
        r'\.to_parquet\s*\(\s*[\'"]([^\'"]+)[\'"]',
        r'\.to_excel\s*\(\s*[\'"]([^\'"]+)[\'"]',
        r'\.to_json\s*\(\s*[\'"]([^\'"]+)[\'"]',
    ],
    'sqlalchemy': [
        r'engine\.execute\s*\(\s*[\'"]([^\'"]+)[\'"]',
        r'session\.execute\s*\(\s*[\'"]([^\'"]+)[\'"]',
        r'connection\.execute\s*\(\s*[\'"]([^\'"]+)[\'"]',
    ],
    'pyspark_read': [
        r'spark\.read\.(?:csv|parquet|json|table|jdbc)\s*\(\s*[\'"]([^\'"]+)[\'"]',
        r'spark\.sql\s*\(\s*[\'"]([^\'"]+)[\'"]',
    ],
    'pyspark_write': [
        r'\.write\.(?:csv|parquet|json|saveAsTable|jdbc)\s*\(\s*[\'"]([^\'"]+)[\'"]',
        r'\.write\.mode\([^\)]*\)\.(?:csv|parquet|json|saveAsTable)\s*\(\s*[\'"]([^\'"]+)[\'"]',
    ],
}


class HydrologistAgent:
    """Agent 2: The Hydrologist - Data Flow & Lineage Analyst.
    
    Constructs the unified data lineage DAG by merging:
    1. Python data flow analysis (pandas/SQLAlchemy/PySpark)
    2. SQL table dependencies (sqlglot)
    3. Pipeline config topology (Airflow/dbt YAML)
    """
    
    def __init__(self, knowledge_graph: KnowledgeGraph):
        self.kg = knowledge_graph
        self.sql_analyzer = SQLLineageAnalyzer()
        self.dag_parser = DAGConfigParser()
        self.ts_analyzer = TreeSitterAnalyzer()
        self._lineage_graph = nx.DiGraph()
        self._dynamic_references: List[Dict[str, Any]] = []
    
    def analyze(self, repo_path: str, target_files: Optional[List[str]] = None) -> Dict[str, Any]:
        """Run the full Hydrologist analysis pipeline.
        
        Returns a summary dict of results.
        """
        repo_root = Path(repo_path).resolve()
        logger.info(f"Hydrologist: Starting data lineage analysis of {repo_root}")
        
        # Source 1: SQL lineage
        logger.info("Hydrologist: Step 1/4 - Analyzing SQL dependencies...")
        sql_result = self._analyze_sql_lineage(str(repo_root), target_files=target_files)
        
        # Source 2: Python data flow
        logger.info("Hydrologist: Step 2/4 - Analyzing Python data flow...")
        python_flows = self._analyze_python_data_flow(str(repo_root), target_files=target_files)
        
        # Source 3: DAG/config topology
        logger.info("Hydrologist: Step 3/4 - Analyzing pipeline configs...")
        config_result = self._analyze_config_topology(str(repo_root), target_files=target_files)
        
        # Merge all sources
        logger.info("Hydrologist: Step 4/4 - Merging lineage sources...")
        self._merge_lineage_sources(sql_result, python_flows, config_result)
        
        # Compute sources and sinks
        sources = self.find_sources()
        sinks = self.find_sinks()
        
        summary = {
            "total_datasets": self._lineage_graph.number_of_nodes(),
            "total_lineage_edges": self._lineage_graph.number_of_edges(),
            "sql_dependencies_found": len(sql_result.dependencies),
            "sql_dbt_refs_found": len(sql_result.dbt_refs),
            "python_data_flows_found": len(python_flows),
            "dynamic_references_unresolved": len(self._dynamic_references),
            "config_pipelines_found": len(config_result.pipelines),
            "data_sources": sources,
            "data_sinks": sinks,
            "sql_files_analyzed": sql_result.files_analyzed,
            "sql_errors": len(sql_result.errors),
        }
        
        logger.info(f"Hydrologist: Analysis complete. "
                    f"{summary['total_datasets']} datasets, "
                    f"{summary['total_lineage_edges']} lineage edges, "
                    f"{len(sources)} sources, {len(sinks)} sinks")
        
        return summary
    
    def _analyze_sql_lineage(self, repo_path: str, target_files: Optional[List[str]] = None) -> SQLLineageResult:
        """Run sqlglot analysis on all SQL files."""
        try:
            result = self.sql_analyzer.analyze_directory(repo_path)
            if target_files is None:
                return result

            scoped = {
                str(Path(p).as_posix()).lstrip("./")
                for p in target_files
                if Path(p).suffix.lower() == ".sql"
            }
            if not scoped:
                return SQLLineageResult()

            result.dependencies = [d for d in result.dependencies if d.source_file in scoped]
            result.dbt_refs = [r for r in result.dbt_refs if r.source_file in scoped]
            result.files_analyzed = len({d.source_file for d in result.dependencies})
            return result
        except Exception as e:
            logger.error(f"SQL lineage analysis failed: {e}")
            return SQLLineageResult(errors=[str(e)])
    
    def _analyze_python_data_flow(self, repo_path: str, target_files: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Detect data read/write operations in Python files."""
        flows = []
        scoped_files: Optional[Set[str]] = None
        if target_files is not None:
            scoped_files = {
                str(Path(p).as_posix()).lstrip("./")
                for p in target_files
                if Path(p).suffix.lower() == ".py"
            }
        
        for py_file in sorted(Path(repo_path).rglob('*.py')):
            if any(p.startswith('.') or p in ('node_modules', '__pycache__', 'venv', '.venv')
                   for p in py_file.parts):
                continue
            
            try:
                content = py_file.read_text(errors='replace')
                rel_path = str(py_file.relative_to(repo_path))
                if scoped_files is not None and rel_path.replace('\\', '/') not in scoped_files:
                    continue

                # Log unresolved dynamic references so users know what static parsing cannot resolve.
                dynamic_hints = [
                    r'execute\s*\(\s*f[\'\"]',
                    r'read_(?:sql|csv|parquet|json)\s*\(\s*[^\'\"\)]',
                    r'to_(?:sql|csv|parquet|json)\s*\(\s*[^\'\"\)]',
                    r'spark\.sql\s*\(\s*[^\'\"\)]',
                ]
                for hint in dynamic_hints:
                    for m in re.finditer(hint, content):
                        line_num = content[:m.start()].count('\n') + 1
                        self._dynamic_references.append({
                            "source_file": rel_path,
                            "line_number": line_num,
                            "reason": "dynamic_reference_cannot_resolve",
                            "preview": m.group(0)[:120],
                        })
                
                for category, patterns in PYTHON_DATA_PATTERNS.items():
                    for pattern in patterns:
                        for match in re.finditer(pattern, content):
                            dataset_ref = match.group(1)
                            line_num = content[:match.start()].count('\n') + 1
                            
                            is_write = 'write' in category or category == 'pandas_write'
                            flow = {
                                'dataset': dataset_ref,
                                'operation': 'write' if is_write else 'read',
                                'category': category,
                                'source_file': rel_path,
                                'line_number': line_num,
                            }
                            flows.append(flow)
                            
            except Exception as e:
                logger.warning(f"Error analyzing Python data flow in {py_file}: {e}")
        
        return flows
    
    def _analyze_config_topology(self, repo_path: str, target_files: Optional[List[str]] = None) -> DAGConfigResult:
        """Parse pipeline configuration files."""
        try:
            result = self.dag_parser.analyze_directory(repo_path)
            if target_files is None:
                return result

            scoped = {
                str(Path(p).as_posix()).lstrip("./")
                for p in target_files
                if Path(p).suffix.lower() in (".yml", ".yaml", ".py", ".sql")
            }
            if not scoped:
                return DAGConfigResult()

            result.pipelines = [p for p in result.pipelines if p.source_file in scoped]
            result.config_relationships = [
                rel for rel in result.config_relationships if rel[0] in scoped
            ]
            result.dbt_models = [m for m in result.dbt_models if m.source_file in scoped]
            return result
        except Exception as e:
            logger.error(f"Config topology analysis failed: {e}")
            return DAGConfigResult(errors=[str(e)])
    
    def _merge_lineage_sources(self, sql_result: SQLLineageResult, 
                                python_flows: List[Dict],
                                config_result: DAGConfigResult):
        """Merge all three data sources into the unified lineage graph."""
        
        # === Merge SQL dependencies ===
        for dep in sql_result.dependencies:
            # Create transformation node for each SQL dependency
            transform_name = f"sql:{dep.source_file}:{dep.line_range[0]}"
            
            transform_node = TransformationNode(
                name=transform_name,
                source_datasets=dep.source_tables,
                target_datasets=dep.target_tables,
                transformation_type="sql_query" if dep.is_read_operation else "sql_write",
                source_file=dep.source_file,
                line_range=dep.line_range,
                sql_query_if_applicable=dep.raw_sql_preview,
            )
            self.kg.add_transformation_node(transform_node)
            
            for source_table in dep.source_tables:
                # Add dataset node
                ds_node = DatasetNode(name=source_table, storage_type="table", source_file=dep.source_file)
                self.kg.add_dataset_node(ds_node)
                self._lineage_graph.add_node(source_table, node_type="dataset", storage_type="table")
                
                # Edge: transformation CONSUMES dataset
                self._lineage_graph.add_edge(source_table, transform_name,
                    edge_type="consumes", transformation_type="sql_query",
                    source_file=dep.source_file, line_range=dep.line_range)
                self.kg.add_consumes_edge(ConsumesEdge(
                    source=transform_name, target=source_table, source_file=dep.source_file))
            
            for target_table in dep.target_tables:
                ds_node = DatasetNode(name=target_table, storage_type="table", source_file=dep.source_file)
                self.kg.add_dataset_node(ds_node)
                self._lineage_graph.add_node(target_table, node_type="dataset", storage_type="table")
                
                # Edge: transformation PRODUCES dataset
                self._lineage_graph.add_edge(transform_name, target_table,
                    edge_type="produces", transformation_type="sql_query",
                    source_file=dep.source_file, line_range=dep.line_range)
                self.kg.add_produces_edge(ProducesEdge(
                    source=transform_name, target=target_table,
                    transformation_type="sql_query", source_file=dep.source_file))
        
        # === Merge dbt refs as lineage edges ===
        for ref in sql_result.dbt_refs:
            model_name = Path(ref.source_file).stem
            
            if ref.ref_type == "ref":
                # ref('model') means current model depends on 'model'
                self._lineage_graph.add_node(ref.target, node_type="dataset", storage_type="table")
                self._lineage_graph.add_node(model_name, node_type="dataset", storage_type="table")
                self._lineage_graph.add_edge(ref.target, model_name,
                    edge_type="dbt_ref", source_file=ref.source_file, 
                    line_number=ref.line_number, transformation_type="dbt_model")
                
                ds_source = DatasetNode(name=ref.target, storage_type="table")
                ds_target = DatasetNode(name=model_name, storage_type="table", source_file=ref.source_file)
                self.kg.add_dataset_node(ds_source)
                self.kg.add_dataset_node(ds_target)
            
            elif ref.ref_type == "source":
                self._lineage_graph.add_node(ref.target, node_type="dataset", 
                    storage_type="table", is_source=True)
                self._lineage_graph.add_node(model_name, node_type="dataset", storage_type="table")
                self._lineage_graph.add_edge(ref.target, model_name,
                    edge_type="dbt_source", source_file=ref.source_file,
                    transformation_type="dbt_model")
                
                ds_source = DatasetNode(name=ref.target, storage_type="table", is_source_of_truth=True)
                self.kg.add_dataset_node(ds_source)
        
        # === Merge Python data flows ===
        for flow in python_flows:
            dataset = flow['dataset']
            source_file = flow['source_file']
            transform_name = f"python:{source_file}:{flow['line_number']}"

            transform_node = TransformationNode(
                name=transform_name,
                source_datasets=[dataset] if flow['operation'] == 'read' else [],
                target_datasets=[dataset] if flow['operation'] == 'write' else [],
                transformation_type="python_transform",
                source_file=source_file,
                line_range=(flow['line_number'], flow['line_number']),
            )
            self.kg.add_transformation_node(transform_node)
            
            self._lineage_graph.add_node(dataset, node_type="dataset",
                storage_type="file" if '/' in dataset or '.' in dataset else "table")
            
            if flow['operation'] == 'read':
                self._lineage_graph.add_edge(dataset, transform_name,
                    edge_type="python_read", source_file=source_file,
                    line_number=flow['line_number'], transformation_type="python_transform")
                self.kg.add_consumes_edge(ConsumesEdge(
                    source=transform_name,
                    target=dataset,
                    source_file=source_file,
                    line_range=(flow['line_number'], flow['line_number']),
                ))
            else:
                self._lineage_graph.add_edge(transform_name, dataset,
                    edge_type="python_write", source_file=source_file,
                    line_number=flow['line_number'], transformation_type="python_transform")
                self.kg.add_produces_edge(ProducesEdge(
                    source=transform_name,
                    target=dataset,
                    transformation_type="python_transform",
                    source_file=source_file,
                    line_range=(flow['line_number'], flow['line_number']),
                ))
            
            ds_node = DatasetNode(
                name=dataset,
                storage_type="file" if '/' in dataset or '\\' in dataset else "table",
                source_file=source_file,
            )
            self.kg.add_dataset_node(ds_node)
        
        # === Merge config topology ===
        for pipeline in config_result.pipelines:
            for task in pipeline.tasks:
                task_id = f"task:{pipeline.pipeline_id}:{task.task_id}"
                self._lineage_graph.add_node(task_id, node_type="task",
                    operator=task.operator_type, pipeline=pipeline.pipeline_id)

                self.kg.add_transformation_node(TransformationNode(
                    name=task_id,
                    transformation_type="dag_task",
                    source_file=pipeline.source_file,
                    line_range=(task.line_number, task.line_number),
                ))
                
                for upstream in task.upstream_tasks:
                    upstream_id = f"task:{pipeline.pipeline_id}:{upstream}"
                    self._lineage_graph.add_edge(upstream_id, task_id,
                        edge_type="task_dependency", pipeline=pipeline.pipeline_id,
                        source_file=pipeline.source_file, transformation_type="dag_task")
        
        # Add config relationships
        for config_file, target, rel_type in config_result.config_relationships:
            self.kg.add_configures_edge(ConfiguresEdge(
                source=config_file, target=target, config_keys=[rel_type], source_file=config_file))
        
        # Add dbt model metadata as enrichment
        for model in config_result.dbt_models:
            self._lineage_graph.add_node(model.name, node_type="dataset",
                storage_type="table", description=model.description,
                materialization=model.materialization)
    
    def blast_radius(self, node_id: str) -> Dict[str, Any]:
        """BFS/DFS from a node to find all downstream dependents with paths.
        
        Returns dict with:
        - affected_nodes: list of downstream node IDs
        - paths: dict mapping each affected node to the path from the source
        - depth: max depth of impact
        """
        if node_id not in self._lineage_graph:
            # Try partial match
            matches = [n for n in self._lineage_graph.nodes() if node_id in n]
            if matches:
                node_id = matches[0]
                logger.info(f"Resolved to node: {node_id}")
            else:
                return {"affected_nodes": [], "paths": {}, "depth": 0,
                        "error": f"Node '{node_id}' not found in lineage graph"}
        
        affected = []
        paths = {}
        visited = set()
        queue = deque([(node_id, [node_id], 0)])
        max_depth = 0
        
        while queue:
            current, path, depth = queue.popleft()
            
            if current in visited:
                continue
            visited.add(current)
            
            if current != node_id:
                affected.append(current)
                paths[current] = path
                max_depth = max(max_depth, depth)
            
            for successor in self._lineage_graph.successors(current):
                if successor not in visited:
                    queue.append((successor, path + [successor], depth + 1))
        
        return {
            "source_node": node_id,
            "affected_nodes": affected,
            "paths": paths,
            "depth": max_depth,
            "total_affected": len(affected),
        }
    
    def find_sources(self) -> List[str]:
        """Find data source nodes (in-degree=0): entry points of the data system."""
        return [n for n in self._lineage_graph.nodes()
                if self._lineage_graph.in_degree(n) == 0 and 
                self._lineage_graph.out_degree(n) > 0]
    
    def find_sinks(self) -> List[str]:
        """Find data sink nodes (out-degree=0): exit points of the data system."""
        return [n for n in self._lineage_graph.nodes()
                if self._lineage_graph.out_degree(n) == 0 and
                self._lineage_graph.in_degree(n) > 0]
    
    def get_lineage_graph(self) -> nx.DiGraph:
        """Return the raw lineage graph."""
        return self._lineage_graph
