import os
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict
from pathlib import Path
from tree_sitter import Language, Parser
import tree_sitter_python as tspython

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

class TreeSitterAnalyzer:
    """Analyzer that uses tree-sitter to extract structural metadata from source files."""

    def __init__(self):
        # Initialize languages and parsers
        self.languages: Dict[str, Language] = {}
        self.parsers: Dict[str, Parser] = {}
        
        try:
            py_lang = Language(tspython.language())
            self.languages["python"] = py_lang
            self.parsers["python"] = Parser(py_lang)
        except Exception as e:
            print(f"Error initializing Python parser: {e}")

    def analyze_file(self, file_path: str) -> AnalysisResult:
        path = Path(file_path)
        ext = path.suffix.lower()
        
        language_name = "unknown"
        if ext == ".py":
            language_name = "python"
        
        if language_name not in self.parsers:
            return AnalysisResult(language=language_name)

        with open(file_path, "r", encoding="utf-8") as f:
            code = f.read()

        parser = self.parsers[language_name]
        tree = parser.parse(bytes(code, "utf8"))
        
        result = AnalysisResult(language=language_name)
        
        if language_name == "python":
            self._analyze_python(tree, code, result)
            
        return result

    def _analyze_python(self, tree, code, result: AnalysisResult):
        """Analyze Python code using a visitor pattern."""
        self._visit_node(tree.root_node, code, result)

    def _visit_node(self, node, code, result: AnalysisResult):
        if node.type == 'import_statement':
            # import a, b.c
            for child in node.children:
                if child.type == 'dotted_name':
                    result.imports.append(ImportInfo(module_path=child.text.decode('utf8'), is_relative=False))
                    
        elif node.type == 'import_from_statement':
            # from ...a.b import c
            is_relative = False
            module_name = ""
            
            # Find relative_import or dotted_name for the module
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
                result.functions.append(FunctionInfo(name=name, line_number=line, is_method=is_method))
                
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
            self._visit_node(child, code, result)
