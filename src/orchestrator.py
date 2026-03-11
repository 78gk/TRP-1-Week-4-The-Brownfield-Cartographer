import logging
import subprocess
import tempfile
import shutil
from pathlib import Path
from typing import Optional, Dict, Any

from rich.console import Console
from rich.logging import RichHandler

from src.graph.knowledge_graph import KnowledgeGraph
from src.agents.surveyor import SurveyorAgent
from src.agents.hydrologist import HydrologistAgent

console = Console()
logger = logging.getLogger(__name__)


class CartographerOrchestrator:
    """Orchestrates the full Brownfield Cartographer analysis pipeline.
    
    Sequences: Surveyor -> Hydrologist
    Serializes outputs to .cartography/ directory.
    """
    
    def __init__(self, output_dir: str = ".cartography"):
        self.output_dir = Path(output_dir)
        self.kg = KnowledgeGraph()
        self._temp_dir: Optional[str] = None
    
    def run(self, target: str) -> Dict[str, Any]:
        """Run the full analysis pipeline on a target codebase.
        
        Args:
            target: Local path or GitHub URL
            
        Returns:
            Summary dict of all results
        """
        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format="%(message)s",
            handlers=[RichHandler(console=console, rich_tracebacks=True)],
        )
        
        # Resolve target path
        repo_path = self._resolve_target(target)
        if not repo_path:
            console.print(f"[red]Error: Could not resolve target: {target}[/red]")
            return {"error": f"Could not resolve target: {target}"}
        
        console.print(f"\n[bold green]🗺️  Brownfield Cartographer[/bold green]")
        console.print(f"[dim]Target: {repo_path}[/dim]\n")
        
        results = {"target": str(repo_path), "errors": []}
        
        try:
            # Phase 1: Surveyor
            console.print("[bold cyan]Phase 1: The Surveyor (Static Structure)[/bold cyan]")
            try:
                surveyor = SurveyorAgent(self.kg)
                surveyor_results = surveyor.analyze(str(repo_path))
                results["surveyor"] = surveyor_results
                console.print(f"[green]  ✓ Surveyor complete: {surveyor_results['total_modules']} modules analyzed[/green]")
            except Exception as e:
                error_msg = f"Surveyor failed: {e}"
                logger.error(error_msg)
                results["errors"].append(error_msg)
                results["surveyor"] = {"error": str(e)}
            
            # Phase 2: Hydrologist
            console.print("[bold cyan]Phase 2: The Hydrologist (Data Lineage)[/bold cyan]")
            try:
                hydrologist = HydrologistAgent(self.kg)
                hydro_results = hydrologist.analyze(str(repo_path))
                results["hydrologist"] = hydro_results
                console.print(f"[green]  ✓ Hydrologist complete: {hydro_results['total_datasets']} datasets, "
                            f"{hydro_results['total_lineage_edges']} lineage edges[/green]")
            except Exception as e:
                error_msg = f"Hydrologist failed: {e}"
                logger.error(error_msg)
                results["errors"].append(error_msg)
                results["hydrologist"] = {"error": str(e)}
            
            # Serialize outputs
            console.print("\n[bold cyan]Serializing outputs...[/bold cyan]")
            self._serialize_outputs()
            
            # Print summary
            summary = self.kg.summary()
            console.print(f"\n[bold green]✓ Analysis complete![/bold green]")
            console.print(f"[dim]Outputs written to {self.output_dir}/[/dim]")
            console.print(f"[dim]  - module_graph.json ({summary['total_nodes']} nodes)[/dim]")
            console.print(f"[dim]  - lineage_graph.json[/dim]")
            
            results["knowledge_graph_summary"] = summary
            
        finally:
            # Cleanup temp dir if we cloned
            if self._temp_dir:
                shutil.rmtree(self._temp_dir, ignore_errors=True)
        
        return results
    
    def _resolve_target(self, target: str) -> Optional[Path]:
        """Resolve a target to a local path. Clone if GitHub URL."""
        # Check if it's a URL
        if target.startswith('http://') or target.startswith('https://') or target.startswith('git@'):
            return self._clone_repo(target)
        
        # Local path
        path = Path(target).resolve()
        if path.exists():
            return path
        
        return None
    
    def _clone_repo(self, url: str) -> Optional[Path]:
        """Clone a GitHub repository to a temporary directory."""
        self._temp_dir = tempfile.mkdtemp(prefix="cartographer_")
        clone_path = Path(self._temp_dir) / "repo"
        
        console.print(f"[dim]Cloning {url}...[/dim]")
        try:
            result = subprocess.run(
                ['git', 'clone', '--depth', '50', url, str(clone_path)],
                capture_output=True, text=True, timeout=120
            )
            if result.returncode != 0:
                logger.error(f"git clone failed: {result.stderr}")
                return None
            console.print(f"[green]  ✓ Cloned to {clone_path}[/green]")
            return clone_path
        except Exception as e:
            logger.error(f"Clone failed: {e}")
            return None
    
    def _serialize_outputs(self):
        """Serialize all outputs to the .cartography/ directory."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Module graph
        module_graph_path = self.output_dir / "module_graph.json"
        self.kg.serialize_to_json(module_graph_path)
        
        # Lineage graph (from the knowledge graph)
        lineage_graph_path = self.output_dir / "lineage_graph.json"
        self.kg.serialize_to_json(lineage_graph_path)
        
        console.print(f"[green]  ✓ Graphs serialized to {self.output_dir}/[/green]")
