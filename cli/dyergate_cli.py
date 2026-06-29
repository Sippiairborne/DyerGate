#!/usr/bin/env python3
"""
DyerGate CLI — single-binary installer for on-prem enterprise deployments.

Usage:
    dyergate init
    dyergate start [--detach]
    dyergate stop
    dyergate status
    dyergate upgrade <version>
    dyergate backup
    dyergate restore <file>
    dyergate admin create <email>
    dyergate org create <slug> <name>
    dyergate client provision <org> <identity>
"""
import os
import subprocess
import sys
import time
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(help="DyerGate enterprise installer & ops CLI")
console = Console()

DATA_DIR = Path(os.environ.get("DYERGATE_DATA", "./data"))
COMPOSE_FILE = DATA_DIR / "docker-compose.yml"
PID_FILE = DATA_DIR / "dyergate.pid"


@app.command()
def init(
    domain: str = typer.Option("localhost", help="Public domain"),
    admin_email: str = typer.Option(..., help="Initial admin email"),
    db: str = typer.Option("sqlite", help="Database: sqlite or postgres"),
):
    """Initialize a new DyerGate deployment."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    env_path = DATA_DIR / ".env"
    secret = subprocess.run(["openssl", "rand", "-hex", "32"], capture_output=True, text=True).stdout.strip()
    admin_key = subprocess.run(["openssl", "rand", "-hex", "32"], capture_output=True, text=True).stdout.strip()
    env_path.write_text(f"""DATABASE_URL={"sqlite:///./data/dyergate.db" if db == "sqlite" else "postgresql://dyergate:secret@db/dyergate"}
SECRET_KEY={secret}
ADMIN_API_KEY={admin_key}
PUBLIC_BASE_URL=https://{domain}
""")
    console.print(f"[green]✓[/green] Initialized at {DATA_DIR}")
    console.print(f"[yellow]⚠[/yellow] Save your ADMIN_API_KEY: {admin_key}")


@app.command()
def start(detach: bool = typer.Option(True, "--detach/--fg")):
    """Start DyerGate services."""
    if not COMPOSE_FILE.exists():
        console.print("[red]Not initialized. Run 'dyergate init' first.[/red]")
        raise typer.Exit(1)
    subprocess.run(["docker", "compose", "-f", str(COMPOSE_FILE), "up",
                    "-d" if detach else ""], check=True)
    console.print("[green]✓[/green] Started")


@app.command()
def stop():
    """Stop DyerGate services."""
    subprocess.run(["docker", "compose", "-f", str(COMPOSE_FILE), "down"], check=True)
    console.print("[green]✓[/green] Stopped")


@app.command()
def status():
    """Show service status."""
    result = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "ps", "--format", "json"],
        capture_output=True, text=True,
    )
    table = Table(title="DyerGate Services")
    table.add_column("Service")
    table.add_column("State")
    table.add_column("Ports")
    for line in result.stdout.splitlines():
        import json as _json
        try:
            obj = _json.loads(line)
            table.add_row(obj.get("Service", ""), obj.get("State", ""), obj.get("Ports", ""))
        except Exception:
            pass
    console.print(table)


@app.command()
def backup():
    """Create a backup."""
    subprocess.run([sys.executable, "scripts/backup.py"], check=True)
    console.print("[green]✓[/green] Backup complete")


@app.command()
def restore(file: Path):
    """Restore from a backup file."""
    subprocess.run([sys.executable, "scripts/restore.py", str(file)], check=True)
    console.print("[green]✓[/green] Restore complete")


@app.command()
def upgrade(version: str):
    """Upgrade to a specific version."""
    subprocess.run(["docker", "pull", f"ghcr.io/yourorg/dyergate:{version}"], check=True)
    (DATA_DIR / "version").write_text(version)
    subprocess.run(["docker", "compose", "-f", str(COMPOSE_FILE), "up", "-d"], check=True)
    console.print(f"[green]✓[/green] Upgraded to {version}")


if __name__ == "__main__":
    app()
