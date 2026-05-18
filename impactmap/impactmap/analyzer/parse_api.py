"""
parse_api.py
------------
Parses a Python (FastAPI / Flask) or Node (Express) API directory and extracts:
  - HTTP method + path  (from route decorators)
  - Tables touched      (via SQLAlchemy model registry + ORM call patterns)

Two-phase approach for SQLAlchemy projects:
  Phase 1 — scan models.py / models/ to build a registry:
              { "Product": "products", "CartItem": "cart_items", ... }
  Phase 2 — scan route files; for each route handler block detect:
              db.query(Model)        → READ
              db.add(Model(...))     → WRITE
              db.delete(instance)    → WRITE (model inferred from prior query)
              model.attr = value     → WRITE (attribute assignment on ORM object)
              db.query(Model).filter → READ
              + raw SQL fallback for anything that slips through

Output: list of dicts
  { "endpoint": "METHOD /path", "file": str, "tables": [{"name": str, "operations": [str]}] }
"""

import os
import re
import json
from pathlib import Path


# ── Route decorator detection ─────────────────────────────────────────────────

PY_DECORATOR_RE = re.compile(
    r'@(?:app|router)\.(get|post|put|patch|delete|route)\s*\(\s*[\'"](/[^\'"]*)[\'"]'
    r'(?:.*?methods\s*=\s*\[([^\]]+)\])?',
    re.IGNORECASE,
)

# ── Phase 1: Model registry builder ──────────────────────────────────────────
# Looks for:  class Product(Base):  +  __tablename__ = "products"

CLASS_RE = re.compile(r'^class\s+([A-Z][A-Za-z0-9_]*)\s*\(', re.MULTILINE)
TABLENAME_RE = re.compile(r'__tablename__\s*=\s*[\'"]([a-z_][a-z0-9_]*)[\'"]')


def build_model_registry(api_dir: str) -> dict[str, str]:
    """
    Walk api_dir for any .py file, find SQLAlchemy model classes and their
    __tablename__, return { "ModelName": "table_name" }.
    """
    registry: dict[str, str] = {}
    for root, _, files in os.walk(api_dir):
        for fname in files:
            if not fname.endswith(".py"):
                continue
            text = Path(root, fname).read_text(errors="ignore")
            # Split on class definitions so we can look for __tablename__ within each
            chunks = CLASS_RE.split(text)
            # chunks: [before_first_class, ClassName1, body1, ClassName2, body2, ...]
            i = 1
            while i < len(chunks) - 1:
                class_name = chunks[i]
                class_body = chunks[i + 1]
                tn_m = TABLENAME_RE.search(class_body)
                if tn_m:
                    registry[class_name] = tn_m.group(1)
                i += 2
    return registry


# ── Phase 2: ORM call pattern matching ───────────────────────────────────────

# db.query(Model) or db.query(Model, OtherModel)
ORM_QUERY_RE = re.compile(
    r'\bdb\.query\s*\(\s*([A-Z][A-Za-z0-9_]*)(?:\s*,\s*([A-Z][A-Za-z0-9_]*))?\s*\)'
)
# db.add(Model(...)) or db.add(variable)  — for add we need the constructor call nearby
ORM_ADD_RE = re.compile(r'\bdb\.add\s*\(\s*([A-Z][A-Za-z0-9_]*)\s*\(')
# db.delete(something)  — we infer the model from a prior query in the same block
ORM_DELETE_RE = re.compile(r'\bdb\.delete\s*\(')
# Attribute mutation on a known ORM object:  product.stock_qty -= 1
# Detected as: identifier.attribute = / += / -= / etc.
ORM_ATTR_WRITE_RE = re.compile(r'\b([a-z_][a-z0-9_]*)\.([a-z_][a-z0-9_]*)\s*(?:\+|-|\*)?=')

# Raw SQL fallback (still useful when devs mix ORM + raw queries)
SQL_TABLE_PATTERNS = [
    (re.compile(r'\bFROM\s+([a-z_][a-z0-9_]*)\b', re.IGNORECASE), "READ"),
    (re.compile(r'\bJOIN\s+([a-z_][a-z0-9_]*)\b', re.IGNORECASE), "READ"),
    (re.compile(r'\bINSERT\s+INTO\s+([a-z_][a-z0-9_]*)\b', re.IGNORECASE), "WRITE"),
    (re.compile(r'\bUPDATE\s+([a-z_][a-z0-9_]*)\b', re.IGNORECASE), "WRITE"),
    (re.compile(r'\bDELETE\s+FROM\s+([a-z_][a-z0-9_]*)\b', re.IGNORECASE), "WRITE"),
]

IGNORE_CLASSES = {
    "HTTPException", "Request", "Response", "BaseModel", "Optional", "Session",
    "List", "Dict", "Depends", "FastAPI", "APIRouter", "JSONResponse", "Annotated",
    "None", "True", "False", "Exception", "ValueError", "TypeError", "Base",
}


def extract_tables_from_block(
    block: str,
    model_registry: dict[str, str],
    known_tables: set[str] | None = None,
) -> list[dict]:
    """
    Given a route handler block (source text), return
    [{"name": "table_name", "operations": ["READ", "WRITE"]}, ...]
    """
    table_ops: dict[str, set] = {}

    def add(table: str, op: str):
        t = table.lower().strip()
        if not t or t in ("from", "into", "where", "set", "on", "as", "by", "and"):
            return
        if known_tables and t not in known_tables:
            return
        table_ops.setdefault(t, set()).add(op)

    # -- ORM: db.query(Model) → READ
    queried_models: set[str] = set()
    for m in ORM_QUERY_RE.finditer(block):
        for grp in (m.group(1), m.group(2)):
            if grp and grp not in IGNORE_CLASSES and grp in model_registry:
                add(model_registry[grp], "READ")
                queried_models.add(grp)

    # -- ORM: db.add(Model(...)) → WRITE
    for m in ORM_ADD_RE.finditer(block):
        model = m.group(1)
        if model not in IGNORE_CLASSES and model in model_registry:
            add(model_registry[model], "WRITE")

    # -- ORM: db.delete(...) → WRITE on whatever was queried in this block
    if ORM_DELETE_RE.search(block):
        for model in queried_models:
            if model in model_registry:
                add(model_registry[model], "WRITE")

    # -- ORM: attribute assignment on a variable whose name hints at a model
    # e.g.  item.product.stock_qty -= item.quantity  →  product model → WRITE
    for m in ORM_ATTR_WRITE_RE.finditer(block):
        obj_name = m.group(1)           # e.g. "item", "product", "existing"
        # Check if obj_name matches (lowercased) any known model name
        for model_name, table_name in model_registry.items():
            if obj_name == model_name.lower() or obj_name.endswith(model_name.lower()):
                add(table_name, "WRITE")
                break
            # Also check: if the variable is the result of a db.query on that model
            # by checking if the model was queried and the variable looks like an instance
            if model_name in queried_models:
                # heuristic: single-word lowercase var like "product", "order", "item"
                if len(obj_name) > 2 and obj_name.isalpha():
                    add(table_name, "WRITE")
                    break

    # -- Raw SQL fallback
    for pattern, op in SQL_TABLE_PATTERNS:
        for m in pattern.finditer(block):
            add(m.group(1), op)

    return [
        {"name": t, "operations": sorted(ops)}
        for t, ops in sorted(table_ops.items())
    ]


# ── Route block splitter ──────────────────────────────────────────────────────

def split_into_route_blocks(text: str) -> list[tuple[str, str, str]]:
    """
    Split a Python source file into (method, path, block_text) tuples,
    one per route decorator found.
    """
    lines = text.split("\n")
    routes = []
    current_route = None
    current_block: list[str] = []

    for line in lines:
        m = PY_DECORATOR_RE.match(line.strip())
        if m:
            if current_route:
                routes.append((*current_route, "\n".join(current_block)))
            method_raw = m.group(1).upper()
            path = m.group(2)
            if method_raw == "ROUTE" and m.group(3):
                method_raw = (
                    m.group(3).replace('"', '').replace("'", '').split(",")[0].strip().upper()
                )
            current_route = (method_raw, path)
            current_block = [line]
        elif current_route:
            current_block.append(line)

    if current_route:
        routes.append((*current_route, "\n".join(current_block)))

    return routes


# ── Node/Express fallback ─────────────────────────────────────────────────────

NODE_ROUTE_RE = re.compile(
    r'(?:app|router)\.(get|post|put|patch|delete)\s*\(\s*[\'"](/[^\'"]*)[\'"]',
    re.IGNORECASE,
)


def parse_node_file(filepath: Path, known_tables: set[str] | None) -> list[dict]:
    text = filepath.read_text(errors="ignore")
    results = []
    for m in NODE_ROUTE_RE.finditer(text):
        method, path = m.group(1).upper(), m.group(2)
        start = m.start()
        next_m = NODE_ROUTE_RE.search(text, m.end())
        block = text[start: next_m.start() if next_m else len(text)]
        tables = extract_tables_from_block(block, {}, known_tables)
        results.append({"endpoint": f"{method} {path}", "file": str(filepath), "tables": tables})
    return results


# ── Main entry ────────────────────────────────────────────────────────────────

def parse_api_dir(
    api_dir: str,
    known_tables: set[str] | None = None,
) -> list[dict]:
    """
    Walk api_dir, build model registry first, then extract route→table mappings.
    """
    model_registry = build_model_registry(api_dir)
    results = []

    for root, _, files in os.walk(api_dir):
        for fname in files:
            filepath = Path(root) / fname

            if fname.endswith(".py"):
                text = filepath.read_text(errors="ignore")
                blocks = split_into_route_blocks(text)
                for method, path, block in blocks:
                    tables = extract_tables_from_block(block, model_registry, known_tables)
                    results.append({
                        "endpoint": f"{method} {path}",
                        "file": str(filepath.relative_to(api_dir)),
                        "tables": tables,
                    })

            elif fname.endswith(".js") and "node_modules" not in str(filepath):
                results.extend(parse_node_file(filepath, known_tables))

    return results


if __name__ == "__main__":
    import sys
    api_dir = sys.argv[1] if len(sys.argv) > 1 else "../proxy-app/backend"
    data = parse_api_dir(api_dir)
    print(json.dumps(data, indent=2))
