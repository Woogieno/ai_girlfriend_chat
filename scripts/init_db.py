"""Initialize the SQLite database from schema.sql. Idempotent."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "src" / "ai_gf" / "state" / "schema.sql"
DEFAULT_DB = ROOT / "data" / "ai_gf.db"


def init_db(db_path: Path = DEFAULT_DB, schema_path: Path = SCHEMA) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    sql = schema_path.read_text(encoding="utf-8")
    with sqlite3.connect(db_path) as conn:
        conn.executescript(sql)
    print(f"DB initialized: {db_path}")


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DB
    init_db(target)
