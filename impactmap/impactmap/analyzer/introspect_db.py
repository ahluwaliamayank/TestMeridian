"""
introspect_db.py
----------------
Introspects a live Postgres database and returns the same structure
that parse_schema.py used to return from a .sql file.

Queries:
  - information_schema.tables        → table names
  - information_schema.columns       → column names, types, nullable
  - information_schema.table_constraints + key_column_usage → PKs
  - information_schema.referential_constraints +
    information_schema.key_column_usage                     → FKs

Output: list of dicts (identical shape to parse_schema.py output)
  {
    "table": str,
    "columns": [{"name": str, "type": str, "pk": bool, "fk": str | None}],
    "foreign_keys": [{"column": str, "references_table": str, "references_column": str}]
  }

Usage:
  python introspect_db.py postgresql://user:pass@host:5432/dbname
  python introspect_db.py  # uses DATABASE_URL env var
"""

import json
import os
import sys

import psycopg2
import psycopg2.extras


def introspect(dsn: str, schema: str = "public") -> list[dict]:
    conn = psycopg2.connect(dsn, cursor_factory=psycopg2.extras.RealDictCursor)
    cur = conn.cursor()

    # ── 1. All user tables in the schema ─────────────────────────────────────
    cur.execute("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = %s
          AND table_type = 'BASE TABLE'
        ORDER BY table_name
    """, (schema,))
    table_names = [r["table_name"] for r in cur.fetchall()]

    # ── 2. Columns per table ──────────────────────────────────────────────────
    cur.execute("""
        SELECT table_name, column_name, data_type, ordinal_position
        FROM information_schema.columns
        WHERE table_schema = %s
        ORDER BY table_name, ordinal_position
    """, (schema,))
    col_rows = cur.fetchall()

    columns_by_table: dict[str, list[dict]] = {t: [] for t in table_names}
    for row in col_rows:
        tname = row["table_name"]
        if tname in columns_by_table:
            columns_by_table[tname].append({
                "name": row["column_name"],
                "type": row["data_type"].upper(),
                "pk": False,   # filled in below
                "fk": None,    # filled in below
            })

    # ── 3. Primary key columns ────────────────────────────────────────────────
    cur.execute("""
        SELECT kcu.table_name, kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema    = kcu.table_schema
        WHERE tc.constraint_type = 'PRIMARY KEY'
          AND tc.table_schema = %s
    """, (schema,))
    pk_rows = cur.fetchall()

    pk_set: dict[str, set] = {}
    for row in pk_rows:
        pk_set.setdefault(row["table_name"], set()).add(row["column_name"])

    for tname, cols in columns_by_table.items():
        pks = pk_set.get(tname, set())
        for col in cols:
            if col["name"] in pks:
                col["pk"] = True

    # ── 4. Foreign keys ───────────────────────────────────────────────────────
    cur.execute("""
        SELECT
            kcu.table_name         AS from_table,
            kcu.column_name        AS from_column,
            ccu.table_name         AS to_table,
            ccu.column_name        AS to_column
        FROM information_schema.referential_constraints rc
        JOIN information_schema.key_column_usage kcu
          ON rc.constraint_name          = kcu.constraint_name
         AND rc.constraint_schema        = kcu.constraint_schema
        JOIN information_schema.constraint_column_usage ccu
          ON rc.unique_constraint_name   = ccu.constraint_name
         AND rc.unique_constraint_schema = ccu.constraint_schema
        WHERE rc.constraint_schema = %s
        ORDER BY kcu.table_name, kcu.column_name
    """, (schema,))
    fk_rows = cur.fetchall()

    fks_by_table: dict[str, list[dict]] = {t: [] for t in table_names}
    fk_col_map: dict[str, dict[str, str]] = {t: {} for t in table_names}

    for row in fk_rows:
        ft = row["from_table"]
        if ft not in fks_by_table:
            continue
        fks_by_table[ft].append({
            "column":            row["from_column"],
            "references_table":  row["to_table"],
            "references_column": row["to_column"],
        })
        fk_col_map[ft][row["from_column"]] = f"{row['to_table']}.{row['to_column']}"

    # Stamp fk onto column dicts
    for tname, cols in columns_by_table.items():
        for col in cols:
            fk = fk_col_map.get(tname, {}).get(col["name"])
            if fk:
                col["fk"] = fk

    conn.close()

    # ── 5. Assemble output ────────────────────────────────────────────────────
    return [
        {
            "table":        tname,
            "columns":      columns_by_table[tname],
            "foreign_keys": fks_by_table[tname],
        }
        for tname in table_names
    ]


def get_table_names(dsn: str, schema: str = "public") -> set[str]:
    return {t["table"] for t in introspect(dsn, schema)}


if __name__ == "__main__":
    dsn = sys.argv[1] if len(sys.argv) > 1 else os.environ.get(
        "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/impactmap"
    )
    data = introspect(dsn)
    print(json.dumps(data, indent=2))
