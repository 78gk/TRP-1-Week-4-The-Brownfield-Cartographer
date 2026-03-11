from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import Optional, List, Literal
from enum import Enum
from datetime import datetime

class NodeType(str, Enum):
    MODULE = "module"
    DATASET = "dataset"
    FUNCTION = "function"
    TRANSFORMATION = "transformation"

class ModuleNode(BaseModel):
    """Represents a source code file/module in the knowledge graph."""
    model_config = ConfigDict(frozen=False)
    
    node_type: Literal["module"] = "module"
    path: str  # relative path from repo root
    language: str  # "python", "sql", "yaml", "javascript"
    purpose_statement: Optional[str] = None  # filled by Semanticist later
    domain_cluster: Optional[str] = None  # filled by Semanticist later
    complexity_score: float = 0.0  # cyclomatic complexity
    lines_of_code: int = 0
    comment_ratio: float = 0.0  # comments / total lines
    change_velocity_30d: int = 0  # number of commits touching this file in last 30 days
    is_dead_code_candidate: bool = False  # no importers found
    last_modified: Optional[datetime] = None
    imports: List[str] = Field(default_factory=list)  # list of imported module paths
    public_functions: List[str] = Field(default_factory=list)  # public function names
    classes: List[str] = Field(default_factory=list)  # class names
    decorators: List[str] = Field(default_factory=list)  # decorator names found
    
    @field_validator('language')
    @classmethod
    def validate_language(cls, v: str) -> str:
        allowed = {'python', 'sql', 'yaml', 'javascript', 'typescript', 'unknown'}
        if v.lower() not in allowed:
            return 'unknown'
        return v.lower()

class DatasetNode(BaseModel):
    """Represents a data artifact (table, file, stream, API endpoint)."""
    model_config = ConfigDict(frozen=False)
    
    node_type: Literal["dataset"] = "dataset"
    name: str  # fully qualified name (e.g., schema.table_name or file path)
    storage_type: Literal["table", "file", "stream", "api", "unknown"] = "unknown"
    schema_snapshot: Optional[dict] = None  # column names/types if known
    freshness_sla: Optional[str] = None  # e.g., "daily", "hourly"
    owner: Optional[str] = None  # team or person
    is_source_of_truth: bool = False
    source_file: Optional[str] = None  # file where this dataset is defined/created

class FunctionNode(BaseModel):
    """Represents a function or method in the codebase."""
    model_config = ConfigDict(frozen=False)
    
    node_type: Literal["function"] = "function"
    qualified_name: str  # module.class.function_name
    parent_module: str  # path to the containing module
    signature: str = ""  # full signature string
    purpose_statement: Optional[str] = None
    call_count_within_repo: int = 0  # how many times called from other modules
    is_public_api: bool = True  # not prefixed with _
    parameters: List[str] = Field(default_factory=list)
    return_type: Optional[str] = None
    decorators: List[str] = Field(default_factory=list)
    line_number: int = 0

class TransformationNode(BaseModel):
    """Represents a data transformation operation."""
    model_config = ConfigDict(frozen=False)
    
    node_type: Literal["transformation"] = "transformation"
    name: str  # descriptive name
    source_datasets: List[str] = Field(default_factory=list)  # input dataset names
    target_datasets: List[str] = Field(default_factory=list)  # output dataset names
    transformation_type: Literal["sql_query", "python_transform", "dbt_model", "dag_task", "unknown"] = "unknown"
    source_file: str = ""  # file containing this transformation
    line_range: tuple[int, int] = (0, 0)  # start, end line
    sql_query_if_applicable: Optional[str] = None  # the SQL text if SQL-based
