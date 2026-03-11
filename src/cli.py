import click
import sys
import logging
from pathlib import Path


@click.group()
@click.version_option(version="0.1.0")
def main():
    """🗺️ The Brownfield Cartographer - Codebase Intelligence System"""
    pass


@main.command()
@click.argument('target', type=str)
@click.option('--output', '-o', default='.cartography', help='Output directory for artifacts')
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose logging')
def analyze(target: str, output: str, verbose: bool):
    """Analyze a target codebase (local path or GitHub URL).
    
    TARGET can be a local directory path or a GitHub repository URL.
    
    Examples:
        cartographer analyze ./my-repo
        cartographer analyze https://github.com/dbt-labs/jaffle-shop.git
    """
    if verbose:
        logging.basicConfig(level=logging.DEBUG)
    
    from src.orchestrator import CartographerOrchestrator
    
    orchestrator = CartographerOrchestrator(output_dir=output)
    results = orchestrator.run(target)
    
    if results.get("errors"):
        click.echo(f"\n⚠️  Completed with {len(results['errors'])} errors")
        for err in results["errors"]:
            click.echo(f"  - {err}")
        sys.exit(1 if not results.get("surveyor") else 0)
    else:
        click.echo(f"\n✅ Analysis complete! Check {output}/ for outputs.")


if __name__ == "__main__":
    main()
