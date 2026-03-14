import click
import logging
import sys
from pathlib import Path


@click.group()
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose/debug logging')
def main(verbose: bool):
    """The Brownfield Cartographer — Codebase Intelligence System"""
    log_level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )


@main.command()
@click.argument('repo_path')
@click.option('--output', '-o', default='.cartography', help='Output directory for artifacts')
@click.option('--skip-semantics', is_flag=True, help='Skip LLM-powered semantic analysis')
@click.option('--incremental', is_flag=True, help='Only re-analyze files changed since last run')
def analyze(repo_path: str, output: str, skip_semantics: bool, incremental: bool):
    """Analyze a codebase and generate knowledge graph artifacts.
    
    REPO_PATH can be a local directory path or a GitHub URL.
    
    Examples:
        python -m src.cli analyze ./target_repos/jaffle_shop
        python -m src.cli analyze https://github.com/dbt-labs/jaffle_shop.git
        python -m src.cli analyze ./my-repo --skip-semantics --incremental
    """
    from src.orchestrator import CartographyOrchestrator
    
    click.echo("🗺️  Brownfield Cartographer — Starting analysis...")
    click.echo(f"📂 Target: {repo_path}")
    click.echo(f"📁 Output: {output}")
    if skip_semantics:
        click.echo("⏭️  Skipping semantic analysis (LLM calls)")
    if incremental:
        click.echo("🔄 Incremental mode: analyzing only changed files")
    click.echo()
    
    try:
        orchestrator = CartographyOrchestrator(
            repo_path=repo_path, 
            output_dir=output,
            skip_semantics=skip_semantics,
            incremental=incremental
        )
        results = orchestrator.run()
        
        click.echo()
        click.echo("✅ Analysis complete!")
        click.echo("📊 Results summary:")
        for key, value in results.items():
            if isinstance(value, dict):
                click.echo(f"   {key}:")
                for k, v in value.items():
                    click.echo(f"      {k}: {v}")
            else:
                click.echo(f"   {key}: {value}")
        click.echo(f"\n📁 Artifacts written to: {output}/")
        
    except Exception as e:
        click.echo(f"❌ Analysis failed: {e}", err=True)
        logging.exception("Analysis failed")
        sys.exit(1)


@main.command()
@click.option('--graph-dir', '-g', default='.cartography', help='Directory containing knowledge graph artifacts')
def query(graph_dir: str):
    """Launch interactive Navigator to query a previously analyzed codebase.
    
    Requires a prior 'analyze' run to have generated artifacts in the graph directory.
    
    Examples:
        python -m src.cli query
        python -m src.cli query --graph-dir ./my-output
    """
    from src.graph.knowledge_graph import KnowledgeGraph
    from src.agents.navigator import NavigatorAgent
    
    kg = KnowledgeGraph()
    
    # Load serialized graphs
    module_graph_path = Path(graph_dir) / "module_graph.json"
    lineage_graph_path = Path(graph_dir) / "lineage_graph.json"
    
    if not module_graph_path.exists() and not lineage_graph_path.exists():
        click.echo(f"❌ No artifacts found in {graph_dir}/. Run 'analyze' first.", err=True)
        sys.exit(1)
    
    try:
        if module_graph_path.exists():
            kg.deserialize_module_graph(str(module_graph_path))
            click.echo(f"✅ Loaded module graph from {module_graph_path}")
        if lineage_graph_path.exists():
            kg.deserialize_lineage_graph(str(lineage_graph_path))
            click.echo(f"✅ Loaded lineage graph from {lineage_graph_path}")
    except Exception as e:
        click.echo(f"⚠️  Error loading graphs: {e}. Some queries may have limited results.", err=True)
    
    # Try to set up LLM client (optional)
    llm_client = None
    try:
        from src.utils.llm_client import LLMClient
        from src.utils.token_budget import ContextWindowBudget
        budget = ContextWindowBudget(total_budget_usd=0.5)
        llm_client = LLMClient(budget)
        if llm_client.is_available():
            click.echo("🤖 LLM client available for enhanced queries")
        else:
            click.echo("ℹ️  No LLM API key found. Queries will use graph data only.")
            llm_client = None
    except ImportError:
        click.echo("ℹ️  LLM client not available. Queries will use graph data only.")
    
    navigator = NavigatorAgent(knowledge_graph=kg, llm_client=llm_client)
    
    click.echo()
    navigator.interactive_mode()


if __name__ == "__main__":
    main()
