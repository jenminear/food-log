"""
Wipe all user data from food_log.db, leaving the schema intact.

Useful while iterating on the ingredient-resolution / nutrition-lookup
flow, where each test run tends to leave behind recipes, components,
and ingredients with stale data.

Usage:
    python wipe_db.py
"""

import sqlite3

DB_PATH = "food_log.db"

# Order matters: delete child tables (referencing other tables via
# foreign keys) before parent tables.
TABLES = ["components", "meals", "batches", "notes", "recipes", "ingredients"]


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    try:
        for table in TABLES:
            conn.execute(f"DELETE FROM {table}")
            # Reset autoincrement counters so new rows start at id 1 again.
            conn.execute("DELETE FROM sqlite_sequence WHERE name = ?", (table,))
        conn.commit()

        for table in TABLES:
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"{table}: {count} rows")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
