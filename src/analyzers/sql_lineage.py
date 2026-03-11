import re
import logging
from pathlib import Path
from typing import List, Dict, Optional, Set, Tuple
from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp

logger = logging.getLogger(__name__)

SUPPORTED_DIALECTS = ['postgres', 'bigquery', 'snowflake', 'duckdb', 'mysql', 'tsql']

@dataclass
class SQLDependency:
    """A single SQL statement's table dependencies."""
    source_tables: List[str]    # tables read from (FROM, JOIN, CTE source)
    target_tables: List[str]    # tables written to (INTO, CREATE)
    cte_names: List[str]        # CTE alias names (WITH x AS ...)
    source_file: str = ""
    line_range: Tuple[int, int] = (0, 0)
    dialect: str = "postgres"
    is_read_operation: bool = True    # SELECT = True, CREATE/INSERT = False
    raw_sql_preview: str = ""        # first 200 chars

@dataclass
class DbtRef:
    """A dbt ref() or source() reference."""
    ref_type: str            # "ref" or "source"
    target: str              # model name for ref(), or (source_name, table_name) joined
    source_file: str = ""
    line_number: int = 0

@dataclass
class SQLLineageResult:
    """Result of analyzing a SQL file or directory."""
    dependencies: List[SQLDependency] = field(default_factory=list)
    dbt_refs: List[DbtRef] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    files_analyzed: int = 0
    files_failed: int = 0


class SQLLineageAnalyzer:
    """Sqlglot-based SQL dependency extraction.
    
    Parses SQL files and extracts table-level dependencies from query structures.
    Supports multiple SQL dialects and basic dbt ref() pattern recognition.
    """
    
    def __init__(self, default_dialect: str = "postgres"):
        self.default_dialect = default_dialect
        if default_dialect not in SUPPORTED_DIALECTS:
            logger.warning(f"Dialect {default_dialect} not in primary list, falling back to postgres")
            self.default_dialect = "postgres"
    
    def analyze_sql_string(self, sql: str, dialect: Optional[str] = None, 
                           source_file: str = "", line_offset: int = 0) -> List[SQLDependency]:
        """Parse a SQL string and extract table dependencies.
        
        Tries the specified dialect first, then falls back to other dialects.
        """
        dialect = dialect or self.default_dialect
        deps = []
        
        # Try parsing with specified dialect, then fallback
        parsed = None
        used_dialect = dialect
        for try_dialect in [dialect] + [d for d in SUPPORTED_DIALECTS if d != dialect]:
            try:
                parsed = sqlglot.parse(sql, dialect=try_dialect)
                used_dialect = try_dialect
                break
            except sqlglot.errors.ParseError:
                continue
            except Exception:
                continue
        
        if not parsed:
            logger.warning(f"Could not parse SQL from {source_file}: unparseable by any dialect")
            return deps
        
        search_offset = 0
        for statement in parsed:
            if statement is None:
                continue
            try:
                statement_sql = statement.sql(dialect=used_dialect)
                stmt_line_range, search_offset = self._locate_statement_line_range(sql, statement_sql, search_offset, line_offset)
                dep = self._extract_from_statement(
                    statement,
                    used_dialect,
                    source_file,
                    stmt_line_range,
                )
                if dep.source_tables or dep.target_tables:
                    deps.append(dep)
            except Exception as e:
                logger.warning(f"Error extracting deps from statement in {source_file}: {e}")
        
        return deps
    
    def _extract_from_statement(self, statement, dialect: str, 
                                 source_file: str, line_range: Tuple[int, int]) -> SQLDependency:
        """Extract source and target tables from a parsed SQL statement."""
        source_tables: Set[str] = set()
        target_tables: Set[str] = set()
        cte_names: Set[str] = set()
        is_read = True
        
        # Extract CTEs
        for cte in statement.find_all(exp.CTE):
            alias = cte.alias
            if alias:
                cte_names.add(alias)
        
        # Extract source tables (FROM, JOIN)
        for table in statement.find_all(exp.Table):
            table_name = self._get_table_name(table)
            if table_name and table_name not in cte_names:
                # Determine if this is a source or target
                parent = table.parent
                is_target = False
                while parent:
                    if isinstance(parent, (exp.Insert, exp.Create)):
                        is_target = True
                        break
                    if isinstance(parent, exp.Into):
                        is_target = True
                        break
                    parent = parent.parent
                
                if is_target:
                    target_tables.add(table_name)
                    is_read = False
                else:
                    source_tables.add(table_name)
        
        # Check for CREATE TABLE ... AS
        if isinstance(statement, exp.Create):
            is_read = False
            # The table being created
            this = statement.this
            if isinstance(this, exp.Schema):
                this = this.this
            if isinstance(this, exp.Table):
                target_tables.add(self._get_table_name(this) or "")
        
        # Check for INSERT INTO
        if isinstance(statement, exp.Insert):
            is_read = False
            this = statement.this
            if isinstance(this, exp.Table):
                target_tables.add(self._get_table_name(this) or "")
        
        raw_preview = statement.sql(dialect=dialect)[:200] if statement else ""
        
        return SQLDependency(
            source_tables=sorted(source_tables),
            target_tables=sorted(target_tables),
            cte_names=sorted(cte_names),
            source_file=source_file,
            line_range=line_range,
            dialect=dialect,
            is_read_operation=is_read,
            raw_sql_preview=raw_preview,
        )

    def _locate_statement_line_range(
        self,
        full_sql: str,
        statement_sql: str,
        search_offset: int,
        line_offset: int,
    ) -> Tuple[Tuple[int, int], int]:
        """Approximate the original line range for a parsed statement."""
        normalized_statement = statement_sql.strip()
        if not normalized_statement:
            return (line_offset, line_offset), search_offset

        position = full_sql.find(normalized_statement, search_offset)
        if position == -1:
            start_line = max(1, line_offset + 1)
            return (start_line, start_line), search_offset

        start_line = full_sql[:position].count('\n') + 1 + line_offset
        end_line = start_line + normalized_statement.count('\n')
        return (start_line, end_line), position + len(normalized_statement)
    
    def _get_table_name(self, table: exp.Table) -> Optional[str]:
        """Extract fully qualified table name from a Table expression."""
        parts = []
        if table.catalog:
            parts.append(table.catalog)
        if table.db:
            parts.append(table.db)
        if table.name:
            parts.append(table.name)
        
        name = '.'.join(parts) if parts else None
        # Filter out common non-table references
        if name and name.upper() in ('DUAL', 'INFORMATION_SCHEMA', 'PG_CATALOG'):
            return None
        return name
    
    def extract_dbt_refs(self, sql_content: str, source_file: str = "") -> List[DbtRef]:
        """Extract dbt ref() and source() patterns from SQL content.
        
        Uses regex since Jinja templating is not valid SQL.
        """
        refs = []
        
        # Match {{ ref('model_name') }} or {{ ref("model_name") }}
        ref_pattern = r"\{\{\s*ref\s*\(\s*['\"]([^'\"]+)['\"]\s*\)\s*\}\}"
        for match in re.finditer(ref_pattern, sql_content):
            line_num = sql_content[:match.start()].count('\n') + 1
            refs.append(DbtRef(
                ref_type="ref",
                target=match.group(1),
                source_file=source_file,
                line_number=line_num,
            ))
        
        # Match {{ source('source_name', 'table_name') }}
        source_pattern = r"\{\{\s*source\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*\)\s*\}\}"
        for match in re.finditer(source_pattern, sql_content):
            line_num = sql_content[:match.start()].count('\n') + 1
            refs.append(DbtRef(
                ref_type="source",
                target=f"{match.group(1)}.{match.group(2)}",
                source_file=source_file,
                line_number=line_num,
            ))
        
        return refs
    
    def analyze_file(self, file_path: str, dialect: Optional[str] = None) -> SQLLineageResult:
        """Analyze a single SQL file."""
        result = SQLLineageResult()
        
        try:
            content = Path(file_path).read_text(errors='replace')
        except Exception as e:
            result.errors.append(f"Could not read {file_path}: {e}")
            result.files_failed += 1
            return result
        
        result.files_analyzed += 1
        
        # Extract dbt refs first (before stripping Jinja)
        result.dbt_refs.extend(self.extract_dbt_refs(content, source_file=file_path))
        
        # Strip Jinja templating for sqlglot parsing
        clean_sql = self._strip_jinja(content)
        
        # Parse SQL
        deps = self.analyze_sql_string(clean_sql, dialect=dialect, source_file=file_path)
        result.dependencies.extend(deps)
        
        # If we found dbt refs but no sqlglot deps, create dependency entries from refs
        if result.dbt_refs and not deps:
            ref_sources = [r.target for r in result.dbt_refs if r.ref_type == "ref"]
            source_sources = [r.target for r in result.dbt_refs if r.ref_type == "source"]
            
            # The current file is the target model
            model_name = Path(file_path).stem
            if ref_sources or source_sources:
                result.dependencies.append(SQLDependency(
                    source_tables=ref_sources + source_sources,
                    target_tables=[model_name],
                    cte_names=[],
                    source_file=file_path,
                    line_range=(1, max(1, content.count('\n') + 1)),
                    dialect=dialect or self.default_dialect,
                    is_read_operation=False,
                ))
        
        return result
    
    def analyze_directory(self, dir_path: str, dialect: Optional[str] = None) -> SQLLineageResult:
        """Analyze all .sql files in a directory tree."""
        combined = SQLLineageResult()
        
        for sql_file in sorted(Path(dir_path).rglob('*.sql')):
            if any(p.startswith('.') for p in sql_file.parts):
                continue
            
            try:
                file_result = self.analyze_file(str(sql_file), dialect=dialect)
                combined.dependencies.extend(file_result.dependencies)
                combined.dbt_refs.extend(file_result.dbt_refs)
                combined.errors.extend(file_result.errors)
                combined.files_analyzed += file_result.files_analyzed
                combined.files_failed += file_result.files_failed
            except Exception as e:
                logger.error(f"Failed to analyze SQL file {sql_file}: {e}")
                combined.errors.append(f"Failed: {sql_file}: {e}")
                combined.files_failed += 1
        
        return combined
    
    def _strip_jinja(self, content: str) -> str:
        """Remove Jinja2 template tags from SQL content for parsing."""
        # Remove {% ... %} blocks
        clean = re.sub(r'\{%.*?%\}', '', content, flags=re.DOTALL)
        # Remove {{ ... }} expressions, replace with placeholder table name
        clean = re.sub(r'\{\{.*?\}\}', 'JINJA_PLACEHOLDER', clean, flags=re.DOTALL)
        # Remove {# ... #} comments
        clean = re.sub(r'\{#.*?#\}', '', clean, flags=re.DOTALL)
        return clean
    
    def get_all_tables(self, result: SQLLineageResult) -> Dict[str, str]:
        """Get a mapping of all discovered tables with their role (source/target)."""
        tables = {}
        for dep in result.dependencies:
            for t in dep.source_tables:
                tables[t] = tables.get(t, "source")
            for t in dep.target_tables:
                tables[t] = "target"  # override - if it's a target anywhere, mark as target
        return tables
