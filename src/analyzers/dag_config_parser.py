import re
import logging
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass, field
import yaml

logger = logging.getLogger(__name__)

@dataclass
class PipelineTask:
    """A single task/step in a pipeline."""
    task_id: str
    operator_type: str = ""       # e.g., PythonOperator, BashOperator
    upstream_tasks: List[str] = field(default_factory=list)
    downstream_tasks: List[str] = field(default_factory=list)
    source_file: str = ""
    line_number: int = 0
    config: Dict[str, Any] = field(default_factory=dict)

@dataclass
class PipelineDefinition:
    """A complete pipeline/DAG definition."""
    pipeline_id: str
    pipeline_type: str  # "airflow_dag", "dbt_project", "prefect_flow"
    tasks: List[PipelineTask] = field(default_factory=list)
    source_file: str = ""
    schedule: Optional[str] = None
    description: Optional[str] = None
    tags: List[str] = field(default_factory=list)

@dataclass
class DbtModel:
    """A dbt model definition from schema.yml."""
    name: str
    description: str = ""
    columns: List[Dict[str, str]] = field(default_factory=list)
    tests: List[str] = field(default_factory=list)
    depends_on: List[str] = field(default_factory=list)  # from ref() analysis
    source_file: str = ""
    materialization: str = "view"

@dataclass
class DbtSource:
    """A dbt source definition from schema.yml."""
    source_name: str
    table_name: str
    description: str = ""
    schema_name: str = ""
    database: str = ""
    source_file: str = ""

@dataclass
class DAGConfigResult:
    """Result of analyzing DAG/pipeline configuration files."""
    pipelines: List[PipelineDefinition] = field(default_factory=list)
    dbt_models: List[DbtModel] = field(default_factory=list)
    dbt_sources: List[DbtSource] = field(default_factory=list)
    config_relationships: List[Tuple[str, str, str]] = field(default_factory=list)  # (config_file, target, relationship_type)
    errors: List[str] = field(default_factory=list)


class DAGConfigParser:
    """Parser for pipeline configuration files (Airflow, dbt, Prefect)."""
    
    def analyze_directory(self, dir_path: str) -> DAGConfigResult:
        """Analyze all relevant config files in a directory."""
        result = DAGConfigResult()
        root = Path(dir_path)
        
        # Parse dbt schema.yml and dbt_project.yml files
        for yml_file in root.rglob('*.yml'):
            if any(p.startswith('.') for p in yml_file.parts):
                continue
            try:
                self._parse_yaml_config(yml_file, result)
            except Exception as e:
                logger.warning(f"Error parsing {yml_file}: {e}")
                result.errors.append(f"{yml_file}: {e}")
        
        for yaml_file in root.rglob('*.yaml'):
            if any(p.startswith('.') for p in yaml_file.parts):
                continue
            try:
                self._parse_yaml_config(yaml_file, result)
            except Exception as e:
                logger.warning(f"Error parsing {yaml_file}: {e}")
                result.errors.append(f"{yaml_file}: {e}")
        
        # Parse Airflow DAG files
        for py_file in root.rglob('*.py'):
            if any(p.startswith('.') for p in py_file.parts):
                continue
            try:
                content = py_file.read_text(errors='replace')
                if self._is_airflow_dag(content):
                    self._parse_airflow_dag(py_file, content, result)
            except Exception as e:
                logger.warning(f"Error parsing Airflow DAG {py_file}: {e}")
                result.errors.append(f"{py_file}: {e}")
        
        return result
    
    def _parse_yaml_config(self, file_path: Path, result: DAGConfigResult):
        """Parse a YAML file and extract relevant config."""
        try:
            content = file_path.read_text(errors='replace')
            data = yaml.safe_load(content)
        except yaml.YAMLError as e:
            logger.warning(f"Invalid YAML in {file_path}: {e}")
            result.errors.append(f"YAML parse error in {file_path}: {e}")
            return
        
        if not isinstance(data, dict):
            return
        
        # dbt schema.yml with models
        if 'models' in data:
            self._extract_dbt_models(data['models'], str(file_path), result)
        
        # dbt schema.yml with sources
        if 'sources' in data:
            self._extract_dbt_sources(data['sources'], str(file_path), result)
        
        # dbt_project.yml
        if 'name' in data and 'version' in data and ('model-paths' in data or 'models' in data):
            pipeline = PipelineDefinition(
                pipeline_id=data.get('name', 'unknown'),
                pipeline_type='dbt_project',
                source_file=str(file_path),
                description=data.get('description', ''),
            )
            result.pipelines.append(pipeline)
            result.config_relationships.append(
                (str(file_path), data.get('name', 'unknown'), 'defines_project')
            )
        
        # Airflow YAML configs (docker-compose, connections, etc.)
        if 'dags' in data or 'connections' in data:
            for key in ('dags', 'connections', 'pools', 'variables'):
                if key in data:
                    result.config_relationships.append(
                        (str(file_path), key, 'configures')
                    )
    
    def _extract_dbt_models(self, models_data, source_file: str, result: DAGConfigResult):
        """Extract dbt model definitions from schema.yml models section."""
        if not isinstance(models_data, list):
            return
        
        for model_data in models_data:
            if not isinstance(model_data, dict):
                continue
            
            name = model_data.get('name', '')
            if not name:
                continue
            
            columns = []
            if 'columns' in model_data and isinstance(model_data['columns'], list):
                for col in model_data['columns']:
                    if isinstance(col, dict):
                        columns.append({
                            'name': col.get('name', ''),
                            'description': col.get('description', ''),
                        })
            
            tests = []
            if 'tests' in model_data and isinstance(model_data['tests'], list):
                for test in model_data['tests']:
                    if isinstance(test, str):
                        tests.append(test)
                    elif isinstance(test, dict):
                        tests.extend(test.keys())
            
            model = DbtModel(
                name=name,
                description=model_data.get('description', ''),
                columns=columns,
                tests=tests,
                source_file=source_file,
                materialization=model_data.get('config', {}).get('materialized', 'view') if isinstance(model_data.get('config'), dict) else 'view',
            )
            result.dbt_models.append(model)
    
    def _extract_dbt_sources(self, sources_data, source_file: str, result: DAGConfigResult):
        """Extract dbt source definitions from schema.yml."""
        if not isinstance(sources_data, list):
            return
        
        for source_data in sources_data:
            if not isinstance(source_data, dict):
                continue
            
            source_name = source_data.get('name', '')
            schema = source_data.get('schema', '')
            database = source_data.get('database', '')
            
            tables = source_data.get('tables', [])
            if isinstance(tables, list):
                for table_data in tables:
                    if isinstance(table_data, dict):
                        result.dbt_sources.append(DbtSource(
                            source_name=source_name,
                            table_name=table_data.get('name', ''),
                            description=table_data.get('description', ''),
                            schema_name=schema,
                            database=database,
                            source_file=source_file,
                        ))
    
    def _is_airflow_dag(self, content: str) -> bool:
        """Check if a Python file is likely an Airflow DAG definition."""
        return 'DAG(' in content or 'from airflow' in content
    
    def _parse_airflow_dag(self, file_path: Path, content: str, result: DAGConfigResult):
        """Extract pipeline topology from an Airflow DAG file."""
        # Extract DAG ID
        dag_id_match = re.search(r"DAG\s*\(\s*['\"]([^'\"]+)['\"]", content)
        dag_id = dag_id_match.group(1) if dag_id_match else file_path.stem
        
        # Extract schedule
        schedule_match = re.search(r"schedule[_interval]*\s*=\s*['\"]([^'\"]+)['\"]", content)
        schedule = schedule_match.group(1) if schedule_match else None
        
        pipeline = PipelineDefinition(
            pipeline_id=dag_id,
            pipeline_type='airflow_dag',
            source_file=str(file_path),
            schedule=schedule,
        )
        
        # Extract task definitions
        task_pattern = r"(\w+)\s*=\s*(\w+(?:Operator|Sensor|Task))\s*\("
        for match in re.finditer(task_pattern, content):
            task_var = match.group(1)
            operator = match.group(2)
            
            # Find task_id
            task_id_match = re.search(
                rf"{task_var}\s*=\s*\w+\(.*?task_id\s*=\s*['\"]([^'\"]+)['\"]",
                content, re.DOTALL
            )
            task_id = task_id_match.group(1) if task_id_match else task_var
            
            pipeline.tasks.append(PipelineTask(
                task_id=task_id,
                operator_type=operator,
                source_file=str(file_path),
                line_number=content[:match.start()].count('\n') + 1,
            ))
        
        # Extract task dependencies (>> operator)
        dep_pattern = r"(\w+)\s*>>\s*(\w+)"
        for match in re.finditer(dep_pattern, content):
            upstream = match.group(1)
            downstream = match.group(2)
            for task in pipeline.tasks:
                if task.task_id == upstream or any(t == upstream for t in [task.task_id]):
                    task.downstream_tasks.append(downstream)
                if task.task_id == downstream:
                    task.upstream_tasks.append(upstream)
        
        if pipeline.tasks:
            result.pipelines.append(pipeline)
            result.config_relationships.append(
                (str(file_path), dag_id, 'defines_dag')
            )
