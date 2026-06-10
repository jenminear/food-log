#!/usr/bin/env python3
"""
init_db.py
----------
Initialises (or re-initialises) the Food Log SQLite database.

Usage:
    python init_db.py                     # creates food_log.db in current dir
    python init_db.py --db /path/to.db    # custom path
    python init_db.py --reset             # drop and recreate all tables
"""

import argparse
import sqlite3
import sys
from pathlib import Path

SCHEMA_FILE = Path(__file__).with_name("food_log_schema.sql")
DEFAULT_DB   = Path(__file__).with_name("food_log.db")


def init_database(db_path: Path, reset: bool = False) -> sqlite3.Connection:
    """Create (or open) the database and apply the schema."""

    if reset and db_path.exists():
        print(f"[reset] Removing existing database: {db_path}")
        db_path.unlink()

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")

    sql = SCHEMA_FILE.read_text()
    conn.executescript(sql)
    conn.commit()

    print(f"[ok] Database ready: {db_path}")
    return conn


def verify_schema(conn: sqlite3.Connection) -> None:
    """Print a summary of every table and its columns."""
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tables = [row[0] for row in cur.fetchall()]

    print("\nTables created:")
    for table in tables:
        cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
        col_names = ", ".join(c[1] for c in cols)
        print(f"  {table:20s}  ({col_names})")

    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' ORDER BY name"
    )
    indexes = [row[0] for row in cur.fetchall()]
    print(f"\nIndexes created: {len(indexes)}")
    for idx in indexes:
        print(f"  {idx}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialise the Food Log database.")
    parser.add_argument("--db",    default=str(DEFAULT_DB), help="Path to SQLite db file")
    parser.add_argument("--reset", action="store_true",     help="Drop and recreate all tables")
    args = parser.parse_args()

    db_path = Path(args.db)
    conn = init_database(db_path, reset=args.reset)
    verify_schema(conn)
    conn.close()


if __name__ == "__main__":
    main()
