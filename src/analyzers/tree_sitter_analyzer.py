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

    def analyze_file(self, file_path: str) -> AnalysisResult:
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
            self._analyze_python(tree, code, result)
        elif language_name == "sql":
            self._analyze_sql(tree, code, result)
        elif language_name == "yaml":
            self._analyze_yaml(tree, code, result)
            
        return result

    def _analyze_python(self, tree, code, result: AnalysisResult):
        """Analyze Python code using a visitor pattern."""
        self._visit_python_node(tree.root_node, code, result)

    def _visit_python_node(self, node, code, result: AnalysisResult):
        if node.type == 'import_statement':
            for child in node.children:
                if child.type == 'dotted_name':
                    result.imports.append(ImportInfo(module_path=child.text.decode('utf8'), is_relative=False))
                    
        elif node.type == 'import_from_statement':
            is_relative = False
            module_name = ""
            for child in node.children:
                if child.type == 'relative_import':
                    is_relative = True
                    module_name = child.text.decode('utf8')
                    break
                elif child.type == 'dotted_name':
                    module_name = child.text.decode('utf8')
                    break
            result.imports.append(ImportInfo(module_path=module_name, is_relative=is_relative))
            
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
            self._visit_python_node(child, code, result)

    def _analyze_sql(self, tree, code, result: AnalysisResult):
        """Analyze SQL for table references."""
        # Simple extraction of table references for structural context
        def visit(node):
            if node.type == 'relation':
                table_name = node.text.decode('utf8')
                if 'tables' not in result.metadata:
                    result.metadata['tables'] = []
                result.metadata['tables'].append(table_name)
            for child in node.children:
                visit(child)
        visit(tree.root_node)

    def _analyze_yaml(self, tree, code, result: AnalysisResult):
        """Analyze YAML for key hierarchies."""
        # Extract top-level keys for structural context
        def visit(node):
            if node.type == 'block_mapping_pair':
                key_node = node.child_by_field_name('key')
                if key_node:
                    key = key_node.text.decode('utf8').strip(': ')
                    if 'keys' not in result.metadata:
                        result.metadata['keys'] = []
                    result.metadata['keys'].append(key)
            for child in node.children:
                visit(child)
        visit(tree.root_node)
