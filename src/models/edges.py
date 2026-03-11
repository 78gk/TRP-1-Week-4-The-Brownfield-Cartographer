from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, Literal, List
from enum import Enum

class EdgeType(str, Enum):
    IMPORTS = "imports"           # source_module -> target_module
    PRODUCES = "produces"        # transformation -> dataset
    CONSUMES = "consumes"        # transformation -> dataset (upstream)
    CALLS = "calls"              # function -> function
    CONFIGURES = "configures"    # config_file -> module/pipeline

class ImportEdge(BaseModel):
    model_config = ConfigDict(frozen=False)
    edge_type: Literal["imports"] = "imports"
    source: str  # source module path
    target: str  # target module path
    import_count: int = 1  # weight
    import_names: List[str] = Field(default_factory=list)  # specific symbols imported

class ProducesEdge(BaseModel):
    model_config = ConfigDict(frozen=False)
    edge_type: Literal["produces"] = "produces"
    source: str  # transformation node name
    target: str  # dataset node name
    transformation_type: Optional[str] = None
    source_file: Optional[str] = None
    line_range: Optional[tuple[int, int]] = None

class ConsumesEdge(BaseModel):
    model_config = ConfigDict(frozen=False)
    edge_type: Literal["consumes"] = "consumes"
    source: str  # transformation node name
    target: str  # dataset node name (upstream)
    source_file: Optional[str] = None

class CallsEdge(BaseModel):
    model_config = ConfigDict(frozen=False)
    edge_type: Literal["calls"] = "calls"
    source: str  # caller function qualified name
    target: str  # callee function qualified name
    call_count: int = 1

class ConfiguresEdge(BaseModel):
    model_config = ConfigDict(frozen=False)
    edge_type: Literal["configures"] = "configures"
    source: str  # config file path
    target: str  # module or pipeline being configured
    config_keys: List[str] = Field(default_factory=list)
