import json
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any, Set
import networkx as nx
from networkx.readwrite import json_graph

from src.models.nodes import ModuleNode, DatasetNode, FunctionNode, TransformationNode, NodeType
from src.models.edges import EdgeType, ImportEdge, ProducesEdge, ConsumesEdge, CallsEdge, ConfiguresEdge

logger = logging.getLogger(__name__)

class KnowledgeGraph:
    """Central knowledge graph storage layer wrapping NetworkX.
    
    Designed as a shared service that Surveyor, Hydrologist, and other agents
    can write to and read from. All nodes and edges are typed and validated.
    """
    
    def __init__(self):
        self._graph = nx.DiGraph()
        self._module_nodes: Dict[str, ModuleNode] = {}
        self._dataset_nodes: Dict[str, DatasetNode] = {}
        self._function_nodes: Dict[str, FunctionNode] = {}
        self._transformation_nodes: Dict[str, TransformationNode] = {}
        self.metadata: Dict[str, Any] = {}
    
    @property
    def graph(self) -> nx.DiGraph:
        return self._graph

    @property
    def module_graph(self) -> nx.DiGraph:
        """Derived module/function graph view for architecture analysis."""
        return self._build_filtered_graph(
            node_types={NodeType.MODULE.value, NodeType.FUNCTION.value},
            edge_types={EdgeType.IMPORTS.value, EdgeType.CALLS.value},
        )

    @property
    def lineage_graph(self) -> nx.DiGraph:
        """Derived dataset/transformation graph view for lineage analysis."""
        return self._build_filtered_graph(
            node_types={NodeType.DATASET.value, NodeType.TRANSFORMATION.value},
            edge_types={EdgeType.PRODUCES.value, EdgeType.CONSUMES.value, EdgeType.CONFIGURES.value},
        )
    
    # === TYPED ADD METHODS ===
    
    def add_module_node(self, node: ModuleNode) -> None:
        """Add a ModuleNode to the graph."""
        self._module_nodes[node.path] = node
        self._graph.add_node(
            node.path,
            **node.model_dump(mode='json')
        )
    
    def add_dataset_node(self, node: DatasetNode) -> None:
        """Add a DatasetNode to the graph."""
        self._dataset_nodes[node.name] = node
        self._graph.add_node(
            node.name,
            **node.model_dump(mode='json')
        )
    
    def add_function_node(self, node: FunctionNode) -> None:
        """Add a FunctionNode to the graph."""
        self._function_nodes[node.qualified_name] = node
        self._graph.add_node(
            node.qualified_name,
            **node.model_dump(mode='json')
        )
    
    def add_transformation_node(self, node: TransformationNode) -> None:
        """Add a TransformationNode to the graph."""
        self._transformation_nodes[node.name] = node
        self._graph.add_node(
            node.name,
            **node.model_dump(mode='json')
        )
    
    # === TYPED EDGE METHODS ===
    
    def add_import_edge(self, edge: ImportEdge) -> None:
        self._graph.add_edge(
            edge.source, edge.target,
            **edge.model_dump(mode='json')
        )
    
    def add_produces_edge(self, edge: ProducesEdge) -> None:
        self._graph.add_edge(
            edge.source, edge.target,
            **edge.model_dump(mode='json')
        )
    
    def add_consumes_edge(self, edge: ConsumesEdge) -> None:
        self._graph.add_edge(
            edge.source, edge.target,
            **edge.model_dump(mode='json')
        )
    
    def add_calls_edge(self, edge: CallsEdge) -> None:
        self._graph.add_edge(
            edge.source, edge.target,
            **edge.model_dump(mode='json')
        )
    
    def add_configures_edge(self, edge: ConfiguresEdge) -> None:
        self._graph.add_edge(
            edge.source, edge.target,
            **edge.model_dump(mode='json')
        )

    def _build_filtered_graph(self, node_types: Set[str], edge_types: Set[str]) -> nx.DiGraph:
        """Create a filtered copy of the graph by node and edge types."""
        filtered = self._graph.copy()
        filtered.remove_nodes_from(
            [n for n, d in filtered.nodes(data=True) if d.get("node_type") not in node_types]
        )
        filtered.remove_edges_from(
            [(u, v) for u, v, d in filtered.edges(data=True) if d.get("edge_type") not in edge_types]
        )
        return filtered

    def update_node_attributes(self, node_id: str, **attrs: Any) -> None:
        """Update both the raw graph node attributes and the typed cache."""
        if node_id not in self._graph:
            return

        self._graph.nodes[node_id].update(attrs)
        node_type = self._graph.nodes[node_id].get("node_type")

        if node_type == NodeType.MODULE.value and node_id in self._module_nodes:
            payload = self._module_nodes[node_id].model_dump(mode='python')
            payload.update(attrs)
            self._module_nodes[node_id] = ModuleNode.model_validate(payload)
        elif node_type == NodeType.DATASET.value and node_id in self._dataset_nodes:
            payload = self._dataset_nodes[node_id].model_dump(mode='python')
            payload.update(attrs)
            self._dataset_nodes[node_id] = DatasetNode.model_validate(payload)
        elif node_type == NodeType.FUNCTION.value and node_id in self._function_nodes:
            payload = self._function_nodes[node_id].model_dump(mode='python')
            payload.update(attrs)
            self._function_nodes[node_id] = FunctionNode.model_validate(payload)
        elif node_type == NodeType.TRANSFORMATION.value and node_id in self._transformation_nodes:
            payload = self._transformation_nodes[node_id].model_dump(mode='python')
            payload.update(attrs)
            self._transformation_nodes[node_id] = TransformationNode.model_validate(payload)
    
    # === QUERY METHODS ===
    
    def get_module_nodes(self) -> Dict[str, ModuleNode]:
        return self._module_nodes.copy()
    
    def get_dataset_nodes(self) -> Dict[str, DatasetNode]:
        return self._dataset_nodes.copy()

    def get_function_nodes(self) -> Dict[str, FunctionNode]:
        return self._function_nodes.copy()

    def get_transformation_nodes(self) -> Dict[str, TransformationNode]:
        return self._transformation_nodes.copy()

    def get_all_nodes(self) -> List[Any]:
        """Return all typed node objects across node categories."""
        return [
            *self._module_nodes.values(),
            *self._dataset_nodes.values(),
            *self._function_nodes.values(),
            *self._transformation_nodes.values(),
        ]

    def get_top_modules(self, limit: int = 10) -> List[ModuleNode]:
        """Return module nodes ranked by PageRank score (descending)."""
        modules = list(self._module_nodes.values())
        modules.sort(key=lambda m: (m.pagerank_score, m.path), reverse=True)
        return modules[:limit]

    def get_node_pagerank(self, node_id: str) -> float:
        if node_id in self._module_nodes:
            return float(self._module_nodes[node_id].pagerank_score)
        return float(self._graph.nodes.get(node_id, {}).get("pagerank_score", 0.0))

    def get_lineage_sources(self) -> List[DatasetNode]:
        """Dataset nodes that have no incoming edges in the unified graph."""
        sources: List[DatasetNode] = []
        for dataset_name, dataset_node in self._dataset_nodes.items():
            if dataset_name in self._graph and self._graph.in_degree(dataset_name) == 0:
                sources.append(dataset_node)
        return sources

    def get_lineage_sinks(self) -> List[DatasetNode]:
        """Dataset nodes that have no outgoing edges in the unified graph."""
        sinks: List[DatasetNode] = []
        for dataset_name, dataset_node in self._dataset_nodes.items():
            if dataset_name in self._graph and self._graph.out_degree(dataset_name) == 0:
                sinks.append(dataset_node)
        return sinks

    def find_strongly_connected_components(self) -> List[List[str]]:
        """Return strongly connected components from module import relationships."""
        subgraph = nx.DiGraph()
        for module_path in self._module_nodes:
            subgraph.add_node(module_path)
        for u, v in self.get_edges_by_type(EdgeType.IMPORTS.value):
            if u in self._module_nodes and v in self._module_nodes:
                subgraph.add_edge(u, v)
        return [list(component) for component in nx.strongly_connected_components(subgraph)]
    
    def get_nodes_by_type(self, node_type: str) -> List[str]:
        return [n for n, d in self._graph.nodes(data=True) if d.get('node_type') == node_type]
    
    def get_edges_by_type(self, edge_type: str) -> List[tuple]:
        return [(u, v) for u, v, d in self._graph.edges(data=True) if d.get('edge_type') == edge_type]
    
    def get_successors(self, node_id: str) -> List[str]:
        if node_id in self._graph:
            return list(self._graph.successors(node_id))
        return []
    
    def get_predecessors(self, node_id: str) -> List[str]:
        if node_id in self._graph:
            return list(self._graph.predecessors(node_id))
        return []
    
    # === SERIALIZATION ===
    
    def _serialize_graph(self, graph: nx.DiGraph, filepath: Path) -> None:
        """Serialize any NetworkX DiGraph to JSON."""
        filepath.parent.mkdir(parents=True, exist_ok=True)
        data = json_graph.node_link_data(graph)
        # Convert any non-serializable types
        def make_serializable(obj):
            if isinstance(obj, set):
                return list(obj)
            if isinstance(obj, tuple):
                return list(obj)
            if hasattr(obj, 'isoformat'):
                return obj.isoformat()
            return obj
        
        cleaned = json.loads(json.dumps(data, default=make_serializable))
        with open(filepath, 'w') as f:
            json.dump(cleaned, f, indent=2, default=str)
        logger.info(f"Graph serialized to {filepath} ({graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges)")

    def serialize_to_json(self, filepath: Path) -> None:
        """Serialize the full graph to JSON."""
        self._serialize_graph(self._graph, filepath)

    def serialize_module_graph(self, filepath: str | Path) -> None:
        """Serialize the module/function graph view."""
        self._serialize_graph(self.module_graph, Path(filepath))

    def serialize_lineage_graph(self, filepath: str | Path) -> None:
        """Serialize the lineage graph view."""
        self._serialize_graph(self.lineage_graph, Path(filepath))

    def serialize_filtered_to_json(
        self,
        filepath: Path,
        node_types: Optional[Set[str]] = None,
        edge_types: Optional[Set[str]] = None,
    ) -> None:
        """Serialize a filtered graph view to JSON."""
        filtered = self._graph.copy()

        if node_types is not None:
            filtered.remove_nodes_from(
                [n for n, d in filtered.nodes(data=True) if d.get("node_type") not in node_types]
            )

        if edge_types is not None:
            filtered.remove_edges_from(
                [(u, v) for u, v, d in filtered.edges(data=True) if d.get("edge_type") not in edge_types]
            )

        self._serialize_graph(filtered, filepath)
    
    @classmethod
    def deserialize_from_json(cls, filepath: Path) -> 'KnowledgeGraph':
        """Deserialize a graph from JSON."""
        kg = cls()
        with open(filepath, 'r') as f:
            data = json.load(f)
        kg._graph = json_graph.node_link_graph(data, directed=True)
        # Rebuild typed node dictionaries
        for node_id, node_data in kg._graph.nodes(data=True):
            nt = node_data.get('node_type')
            try:
                # Filter out attributes that are not fields in the model
                # (like 'id' added by NetworkX)
                if nt == 'module':
                    attrs = {k: v for k, v in node_data.items() if k in ModuleNode.model_fields}
                    kg._module_nodes[node_id] = ModuleNode.model_validate(attrs)
                elif nt == 'dataset':
                    attrs = {k: v for k, v in node_data.items() if k in DatasetNode.model_fields}
                    kg._dataset_nodes[node_id] = DatasetNode.model_validate(attrs)
                elif nt == 'function':
                    attrs = {k: v for k, v in node_data.items() if k in FunctionNode.model_fields}
                    kg._function_nodes[node_id] = FunctionNode.model_validate(attrs)
                elif nt == 'transformation':
                    attrs = {k: v for k, v in node_data.items() if k in TransformationNode.model_fields}
                    kg._transformation_nodes[node_id] = TransformationNode.model_validate(attrs)
            except Exception as e:
                logger.warning(f"Could not reconstruct typed node {node_id}: {e}")
        logger.info(f"Graph deserialized from {filepath}")
        return kg

    def _ingest_graph(self, graph: nx.DiGraph) -> None:
        """Merge a loaded graph into this instance and rebuild typed caches."""
        self._graph = nx.compose(self._graph, graph)
        for node_id, node_data in graph.nodes(data=True):
            nt = node_data.get("node_type")
            try:
                if nt == NodeType.MODULE.value:
                    attrs = {k: v for k, v in node_data.items() if k in ModuleNode.model_fields}
                    self._module_nodes[node_id] = ModuleNode.model_validate(attrs)
                elif nt == NodeType.DATASET.value:
                    attrs = {k: v for k, v in node_data.items() if k in DatasetNode.model_fields}
                    self._dataset_nodes[node_id] = DatasetNode.model_validate(attrs)
                elif nt == NodeType.FUNCTION.value:
                    attrs = {k: v for k, v in node_data.items() if k in FunctionNode.model_fields}
                    self._function_nodes[node_id] = FunctionNode.model_validate(attrs)
                elif nt == NodeType.TRANSFORMATION.value:
                    attrs = {k: v for k, v in node_data.items() if k in TransformationNode.model_fields}
                    self._transformation_nodes[node_id] = TransformationNode.model_validate(attrs)
            except Exception as e:
                logger.warning(f"Could not ingest typed node {node_id}: {e}")

    def deserialize_module_graph(self, filepath: str | Path) -> None:
        """Load a previously serialized module graph view into this KG instance."""
        with open(filepath, "r") as f:
            data = json.load(f)
        graph = json_graph.node_link_graph(data, directed=True)
        self._ingest_graph(graph)

    def deserialize_lineage_graph(self, filepath: str | Path) -> None:
        """Load a previously serialized lineage graph view into this KG instance."""
        with open(filepath, "r") as f:
            data = json.load(f)
        graph = json_graph.node_link_graph(data, directed=True)
        self._ingest_graph(graph)
    
    # === STATS ===
    
    def summary(self) -> Dict[str, Any]:
        return {
            "total_nodes": self._graph.number_of_nodes(),
            "total_edges": self._graph.number_of_edges(),
            "module_nodes": len(self._module_nodes),
            "dataset_nodes": len(self._dataset_nodes),
            "function_nodes": len(self._function_nodes),
            "transformation_nodes": len(self._transformation_nodes),
            "edge_type_counts": {
                et.value: len(self.get_edges_by_type(et.value))
                for et in EdgeType
            }
        }
