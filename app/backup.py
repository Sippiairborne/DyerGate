import logging
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from app.config import settings

logger = logging.getLogger("dyergate.backup")


def run_backup() -> str | None:
    """Returns the local backup file path, or None on failure."""
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_dir = Path("./data/backups")
    out_dir.mkdir(parents=True, exist_ok=True)

    if settings.DATABASE_URL.startswith("sqlite"):
        src = settings.DATABASE_URL.replace("sqlite:///", "")
        if not os.path.exists(src):
            logger.error("sqlite db not found: %s", src)
            return None
        dst = out_dir / f"dyergate_{ts}.db"
        # Atomic hot copy via sqlite3 .backup
        try:
            subprocess.run(["sqlite3", src, f".backup '{dst}'"], check=True)
            logger.info("sqlite backup written: %s", dst)
            return str(dst)
        except Exception:
            shutil.copy2(src, dst)
            return str(dst)

    if settings.DATABASE_URL.startswith("postgres"):
        out = out_dir / f"dyergate_{ts}.sql"
        try:
            subprocess.run(["pg_dump", settings.DATABASE_URL, "-f", str(out)], check=True)
            logger.info("pg backup written: %s", out)
            return str(out)
        except Exception as e:
            logger.exception("pg_dump failed: %s", e)
            return None

    return None
