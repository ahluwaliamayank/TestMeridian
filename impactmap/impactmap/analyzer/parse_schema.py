"""
parse_schema.py
---------------
Parses a SQL schema file (.sql) and extracts:
  - Table names
  - Columns (name, type, pk flag)
  - Foreign key relationships

Also supports Prisma schema files (.prisma) and basic SQLAlchemy models.

Output: list of dicts
  {
    "table": str,
    "columns": [{"name": str, "type": str, "pk": bool, "fk": str | None}],
    "foreign_keys": [{"column": str, "references_table": str, "references_column": str}]
  }
"""

import re
import json
from pathlib import Path


# ── SQL parser ────────────────────────────────────────────────────────────────

CREATE_TABLE_RE = re.compile(
    r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?["`]?(\w+)["`]?\s*\((.+?)\)\s*;',
    re.IGNORECASE | re.DOTALL,
)
COLUMN_RE = re.compile(
    r'^\s*["`]?(\w+)["`]?\s+([A-Z][A-Z0-9_\(\),\s]*?)(?:\s+(NOT NULL|DEFAULT[^,]+|UNIQUE|PRIMARY KEY))*\s*,?\s*$',
    re.IGNORECASE | re.MULTILINE,
)
PK_INLINE_RE = re.compile(r'\bPRIMARY\s+KEY\b', re.IGNORECASE)
PK_CONSTRAINT_RE = re.compile(
    r'PRIMARY\s+KEY\s*\(([^)]+)\)', re.IGNORECASE
)
FK_CONSTRAINT_RE = re.compile(
    r'(?:FOREIGN\s+KEY\s*\(([^)]+)\)\s*REFERENCES\s+["`]?(\w+)["`]?\s*\(([^)]+)\)'
    r'|(\w+)\s+\w[^,\n]*REFERENCES\s+(\w+)\s*\((\w+)\))',
    re.IGNORECASE,
)
INLINE_FK_RE = re.compile(
    r'^\s*["`]?(\w+)["`]?\s+\S+.*?REFERENCES\s+["`]?(\w+)["`]?\s*\(["`]?(\w+)["`]?\)',
    re.IGNORECASE | re.MULTILINE,
)


def parse_sql_schema(schema_path: str) -> list[dict]:
    text = Path(schema_path).read_text(errors="ignore")
    # Remove single-line comments
    text = re.sub(r'--[^\n]*', '', text)
    # Remove multi-line comments
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)

    tables = []

    for m in CREATE_TABLE_RE.finditer(text):
        table_name = m.group(1).lower()
        body = m.group(2)

        columns = []
        foreign_keys = []

        # Find explicit PK constraint
        pk_cols = set()
        pk_m = PK_CONSTRAINT_RE.search(body)
        if pk_m:
            pk_cols = {c.strip().strip('"').lower() for c in pk_m.group(1).split(",")}

        # Find FK constraints
        for fk_m in FK_CONSTRAINT_RE.finditer(body):
            if fk_m.group(1):  # FOREIGN KEY (col) REFERENCES tbl(col)
                col = fk_m.group(1).strip().strip('"').lower()
                ref_table = fk_m.group(2).lower()
                ref_col = fk_m.group(3).strip().strip('"').lower()
                foreign_keys.append({"column": col, "references_table": ref_table, "references_column": ref_col})
            else:  # inline REFERENCES
                col = fk_m.group(4).strip().lower()
                ref_table = fk_m.group(5).lower()
                ref_col = fk_m.group(6).lower()
                foreign_keys.append({"column": col, "references_table": ref_table, "references_column": ref_col})

        # Also scan inline REFERENCES in column defs
        for fk_m in INLINE_FK_RE.finditer(body):
            col = fk_m.group(1).lower()
            ref_table = fk_m.group(2).lower()
            ref_col = fk_m.group(3).lower()
            if not any(f["column"] == col for f in foreign_keys):
                foreign_keys.append({"column": col, "references_table": ref_table, "references_column": ref_col})

        fk_col_map = {fk["column"]: f"{fk['references_table']}.{fk['references_column']}" for fk in foreign_keys}

        # Parse individual columns — skip constraint lines
        lines = [l.strip() for l in body.split("\n") if l.strip()]
        for line in lines:
            # Skip pure constraint lines
            if re.match(r'(CONSTRAINT|PRIMARY\s+KEY|FOREIGN\s+KEY|UNIQUE|CHECK|INDEX)\b', line, re.IGNORECASE):
                continue
            # Extract col name + type
            col_m = re.match(r'["`]?(\w+)["`]?\s+([A-Z][A-Z0-9_]*(?:\([^)]*\))?)', line, re.IGNORECASE)
            if not col_m:
                continue
            col_name = col_m.group(1).lower()
            col_type = col_m.group(2).upper()

            is_pk = col_name in pk_cols or bool(PK_INLINE_RE.search(line))
            fk = fk_col_map.get(col_name)

            columns.append({
                "name": col_name,
                "type": col_type,
                "pk": is_pk,
                "fk": fk,
            })

        tables.append({
            "table": table_name,
            "columns": columns,
            "foreign_keys": foreign_keys,
        })

    return tables


# ── Prisma parser ─────────────────────────────────────────────────────────────

PRISMA_MODEL_RE = re.compile(r'model\s+(\w+)\s*\{(.+?)\}', re.DOTALL)
PRISMA_FIELD_RE = re.compile(r'^\s*(\w+)\s+(\w+)(\?)?\s*(.*)', re.MULTILINE)
PRISMA_RELATION_RE = re.compile(r'@relation\(fields:\s*\[([^\]]+)\].*?references:\s*\[([^\]]+)\]', re.DOTALL)


def _pascal_to_snake_plural(name: str) -> str:
    s1 = re.sub(r'(.)([A-Z][a-z]+)', r'\1_\2', name)
    snake = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', s1).lower()
    return snake + "s" if not snake.endswith("s") else snake


def parse_prisma_schema(schema_path: str) -> list[dict]:
    text = Path(schema_path).read_text(errors="ignore")
    tables = []

    for m in PRISMA_MODEL_RE.finditer(text):
        model_name = m.group(1)
        table_name = _pascal_to_snake_plural(model_name)
        body = m.group(2)

        columns = []
        foreign_keys = []

        for field_m in PRISMA_FIELD_RE.finditer(body):
            fname = field_m.group(1)
            ftype = field_m.group(2)
            attrs = field_m.group(4) or ""
            if fname in ("@@", "//"):
                continue
            is_pk = "@id" in attrs
            # Detect relation fields
            rel_m = PRISMA_RELATION_RE.search(attrs)
            fk = None
            if rel_m:
                ref_fields = [f.strip() for f in rel_m.group(2).split(",")]
                ref_table = _pascal_to_snake_plural(ftype)
                for rf in ref_fields:
                    fk = f"{ref_table}.{rf}"
                    foreign_keys.append({"column": fname, "references_table": ref_table, "references_column": rf})
            columns.append({"name": fname, "type": ftype.upper(), "pk": is_pk, "fk": fk})

        tables.append({"table": table_name, "columns": columns, "foreign_keys": foreign_keys})

    return tables


# ── Dispatcher ────────────────────────────────────────────────────────────────

def parse_schema(schema_path: str) -> list[dict]:
    p = Path(schema_path)
    if p.suffix == ".prisma":
        return parse_prisma_schema(schema_path)
    return parse_sql_schema(schema_path)


def get_table_names(schema_path: str) -> set[str]:
    return {t["table"] for t in parse_schema(schema_path)}


if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "proxy-app/schema.sql"
    data = parse_schema(path)
    print(json.dumps(data, indent=2))
