import os
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict, Any
from pathlib import Path
from tree_sitter import Language, Parser
import tree_sitter_python as tspython
import tree_sitter_sql as tssql
import tree_sitter_yaml as tsyaml

logger = logging.getLogger(__name__)

@dataclass
class ImportInfo:
    module_path: str
    is_relative: bool
    symbols: List[str] = field(default_factory=list)
    resolved_path: Optional[str] = None

@dataclass
class FunctionInfo:
    name: str
    line_number: int
    is_method: bool = False
    signature: str = ""
    decorators: List[str] = field(default_factory=list)

@dataclass
class ClassInfo:
    name: str
    bases: List[str]
    line_number: int

@dataclass
class AnalysisResult:
    language: str
    imports: List[ImportInfo] = field(default_factory=list)
    functions: List[FunctionInfo] = field(default_factory=list)
    classes: List[ClassInfo] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

class TreeSitterAnalyzer:
    """Analyzer that uses tree-sitter to extract structural metadata from source files."""

    def __init__(self):
        # Initialize languages and parsers
        self.languages: Dict[str, Language] = {}
        self.parsers: Dict[str, Parser] = {}
        
        try:
            # Python
            py_lang = Language(tspython.language())
            self.languages["python"] = py_lang
            self.parsers["python"] = Parser(py_lang)
            
            # SQL
            sql_lang = Language(tssql.language())
            self.languages["sql"] = sql_lang
            self.parsers["sql"] = Parser(sql_lang)
            
            # YAML
            yaml_lang = Language(tsyaml.language())
            self.languages["yaml"] = yaml_lang
            self.parsers["yaml"] = Parser(yaml_lang)
            
        except Exception as e:
            logger.error(f"Error initializing parsers: {e}")

    def analyze_file(self, file_path: str, repo_root: Optional[str] = None) -> AnalysisResult:
        path = Path(file_path)
        ext = path.suffix.lower()
        
        language_name = "unknown"
        if ext == ".py":
            language_name = "python"
        elif ext == ".sql":
            language_name = "sql"
        elif ext in (".yaml", ".yml"):
            language_name = "yaml"
        
        if language_name not in self.parsers:
            return AnalysisResult(language=language_name)

        try:
            with open(file_path, "r", encoding="utf-8", errors='replace') as f:
                code = f.read()
        except Exception as e:
            logger.error(f"Error reading file {file_path}: {e}")
            return AnalysisResult(language=language_name)

        parser = self.parsers[language_name]
        try:
            tree = parser.parse(bytes(code, "utf8"))
        except Exception as e:
            logger.error(f"Error parsing file {file_path}: {e}")
            return AnalysisResult(language=language_name)
        
        result = AnalysisResult(language=language_name)
        
        if language_name == "python":
            self._analyze_python(tree, code, result, path, Path(repo_root).resolve() if repo_root else None)
        elif language_name == "sql":
            self._analyze_sql(tree, code, result)
        elif language_name == "yaml":
            self._analyze_yaml(tree, code, result)
            
        return result

    def _analyze_python(self, tree, code, result: AnalysisResult, file_path: Path, repo_root: Optional[Path]):
        """Analyze Python code using a visitor pattern."""
        self._visit_python_node(tree.root_node, code, result, file_path, repo_root)

    def _visit_python_node(self, node, code, result: AnalysisResult, file_path: Path, repo_root: Optional[Path]):
        if node.type == 'import_statement':
            statement = node.text.decode('utf8').strip()
            imported_targets = [chunk.strip() for chunk in statement.replace('import', '', 1).split(',')]
            for target in imported_targets:
                module_path = target.split(' as ')[0].strip()
                if not module_path:
                    continue
                result.imports.append(ImportInfo(
                    module_path=module_path,
                    is_relative=False,
                    resolved_path=self._resolve_python_import(module_path, False, file_path, repo_root),
                ))
                    
        elif node.type == 'import_from_statement':
            statement = node.text.decode('utf8').strip()
            module_part = statement[len('from '):].split(' import ', 1)[0].strip()
            symbol_part = statement.split(' import ', 1)[1].strip() if ' import ' in statement else ''
            symbols = [symbol.strip().split(' as ')[0].strip() for symbol in symbol_part.split(',') if symbol.strip()]
            is_relative = module_part.startswith('.')
            full_module_name = module_part
            result.imports.append(ImportInfo(
                module_path=full_module_name,
                is_relative=is_relative,
                symbols=symbols,
                resolved_path=self._resolve_python_import(full_module_name, is_relative, file_path, repo_root),
            ))
            
        elif node.type == 'function_definition':
            name_node = node.child_by_field_name('name')
            if name_node:
                name = name_node.text.decode('utf8')
                line = name_node.start_point[0] + 1
                is_method = False
                p = node.parent
                while p:
                    if p.type == 'class_definition':
                        is_method = True
                        break
                    p = p.parent
                
                # Extract signature (simplified)
                params_node = node.child_by_field_name('parameters')
                sig = f"def {name}{params_node.text.decode('utf8') if params_node else '()'}"
                
                # Extract decorators
                decorators = []
                p = node.prev_sibling
                while p and p.type == 'decorator':
                    decorators.append(p.text.decode('utf8'))
                    p = p.prev_sibling
                
                result.functions.append(FunctionInfo(
                    name=name, 
                    line_number=line, 
                    is_method=is_method,
                    signature=sig,
                    decorators=decorators
                ))
                
        elif node.type == 'class_definition':
            name_node = node.child_by_field_name('name')
            if name_node:
                name = name_node.text.decode('utf8')
                line = name_node.start_point[0] + 1
                bases = []
                arg_list = node.child_by_field_name('superclasses')
                if arg_list:
                    for arg in arg_list.children:
                        if arg.type in ('identifier', 'attribute'):
                            bases.append(arg.text.decode('utf8'))
                result.classes.append(ClassInfo(name=name, bases=bases, line_number=line))
        
        for child in node.children:
            self._visit_python_node(child, code, result, file_path, repo_root)

    def _analyze_sql(self, tree, code, result: AnalysisResult):
        """Analyze SQL for table references."""
        result.metadata.setdefault('table_references', [])
        result.metadata.setdefault('query_structures', [])
        result.metadata.setdefault('cte_names', [])

        def visit(node):
            if node.type in ('select_statement', 'insert_statement', 'update_statement', 'delete_statement'):
                result.metadata['query_structures'].append({
                    'node_type': node.type,
                    'line_range': (node.start_point[0] + 1, node.end_point[0] + 1),
                })
            elif node.type in ('cte', 'common_table_expression'):
                result.metadata['cte_names'].append(node.text.decode('utf8').split()[0])
            elif node.type == 'relation':
                table_name = node.text.decode('utf8')
                parent_type = node.parent.type if node.parent else 'unknown'
                result.metadata['table_references'].append({
                    'name': table_name,
                    'context': parent_type,
                    'line_range': (node.start_point[0] + 1, node.end_point[0] + 1),
                })
            for child in node.children:
                visit(child)
        visit(tree.root_node)

    def _analyze_yaml(self, tree, code, result: AnalysisResult):
        """Analyze YAML for key hierarchies."""
        result.metadata.setdefault('keys', [])
        result.metadata.setdefault('key_paths', [])

        def visit(node, parents: List[str]):
            if node.type == 'block_mapping_pair':
                key_node = node.child_by_field_name('key')
                value_node = node.child_by_field_name('value')
                if key_node:
                    key = key_node.text.decode('utf8').strip(': ')
                    path = parents + [key]
                    result.metadata['keys'].append(key)
                    result.metadata['key_paths'].append('.'.join(path))
                    if value_node:
                        visit(value_node, path)
                    return
            for child in node.children:
                visit(child, parents)

        visit(tree.root_node, [])

    def _resolve_python_import(
        self,
        module_path: str,
        is_relative: bool,
        file_path: Path,
        repo_root: Optional[Path],
    ) -> Optional[str]:
        """Resolve a Python import to a repo-relative file path where possible."""
        if not repo_root:
            return None

        if is_relative:
            leading_dots = len(module_path) - len(module_path.lstrip('.'))
            remainder = module_path.lstrip('.')
            anchor = file_path.parent
            for _ in range(max(leading_dots - 1, 0)):
                anchor = anchor.parent
            candidate_base = anchor / Path(remainder.replace('.', '/')) if remainder else anchor
            for candidate in (candidate_base.with_suffix('.py'), candidate_base / '__init__.py'):
                if candidate.exists():
                    return str(candidate.relative_to(repo_root)).replace('\\', '/')
            return None

        candidate_base = repo_root / Path(module_path.replace('.', '/'))
        for candidate in (candidate_base.with_suffix('.py'), candidate_base / '__init__.py'):
            if candidate.exists():
                return str(candidate.relative_to(repo_root)).replace('\\', '/')
        return None
