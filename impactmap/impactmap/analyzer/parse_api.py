"""
parse_api.py
------------
AST-based parser for FastAPI/Flask (Python) and Express (Node) routes.

For each route handler found, returns:
  { "endpoint": "METHOD /path", "file": str,
    "tables": [{"name": str, "operations": ["READ"/"WRITE"]}] }

Python parsing strategy (stdlib `ast`):
  Phase 1 — walk every .py file's AST, find SQLAlchemy class definitions
            and their __tablename__, build {ModelName: table_name}.
  Phase 2 — for every function with an @app.METHOD / @router.METHOD /
            @app.route(...) decorator:
              - Extract (METHOD, path) from the decorator
              - Walk the function body to track which local variables are
                bound to which model (via `var = db.query(Model)...` and
                `var = Model(...)` constructor calls and `for x in <queried>`)
              - Detect ORM operations:
                  db.query(Model)        → READ on Model.table
                  db.add(Model(...))     → WRITE on Model.table
                  db.add(var)            → WRITE on var's model
                  db.delete(var)         → WRITE on var's model
                  var.attr = / += ...    → WRITE on var's model
                  obj.relationship.attr  → WRITE on relationship's model
              - Raw SQL inside string arguments to call expressions.

Node parsing strategy (tree-sitter-javascript):
  Find every (app|router).METHOD("/path", ...) call expression.
  Apply raw-SQL regex against the call's source range. No ORM support.

Public surface used by build_graph.py:
  parse_api_dir(api_dir, known_tables=None) -> list[dict]
"""

import ast
import os
import re
import json
from pathlib import Path
from typing import Optional, Callable

import tree_sitter_javascript as tsjs
from tree_sitter import Language, Node, Parser


# ── Module-level constants ───────────────────────────────────────────────────

_HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}
_ROUTE_OBJECTS = {"app", "router"}
_ORM_OBJECTS = {"db", "session"}

# Raw SQL fallback — applied to string args of any call expression
_SQL_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'\bFROM\s+([a-z_][a-z0-9_]*)\b', re.IGNORECASE), "READ"),
    (re.compile(r'\bJOIN\s+([a-z_][a-z0-9_]*)\b', re.IGNORECASE), "READ"),
    (re.compile(r'\bINSERT\s+INTO\s+([a-z_][a-z0-9_]*)\b', re.IGNORECASE), "WRITE"),
    (re.compile(r'\bUPDATE\s+([a-z_][a-z0-9_]*)\b', re.IGNORECASE), "WRITE"),
    (re.compile(r'\bDELETE\s+FROM\s+([a-z_][a-z0-9_]*)\b', re.IGNORECASE), "WRITE"),
]


# ── Phase 1: Build model registry (Python) ───────────────────────────────────

def build_model_registry(api_dir: str) -> dict[str, str]:
    """
    Walk api_dir for .py files, parse to AST, find SQLAlchemy model classes
    with `__tablename__ = "..."`. Return {ModelClassName: table_name}.
    """
    registry: dict[str, str] = {}
    for root, _, files in os.walk(api_dir):
        for fname in files:
            if not fname.endswith(".py"):
                continue
            path = Path(root) / fname
            try:
                tree = ast.parse(path.read_text(errors="ignore"), filename=str(path))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    tn = _find_tablename(node.body)
                    if tn:
                        registry[node.name] = tn
    return registry


def _find_tablename(class_body: list[ast.stmt]) -> Optional[str]:
    for stmt in class_body:
        if not isinstance(stmt, ast.Assign):
            continue
        for target in stmt.targets:
            if isinstance(target, ast.Name) and target.id == "__tablename__":
                if isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                    return stmt.value.value
    return None


# ── Phase 2a: Route decorator extraction ─────────────────────────────────────

def _parse_route_decorator(deco: ast.expr) -> Optional[tuple[str, str]]:
    """
    Return (METHOD, path) if `deco` is one of:
        @app.METHOD("/path")  /  @router.METHOD("/path")
        @app.route("/path", methods=["POST"])  (Flask)
    else None.
    """
    if not isinstance(deco, ast.Call) or not isinstance(deco.func, ast.Attribute):
        return None
    obj = deco.func.value
    if not isinstance(obj, ast.Name) or obj.id not in _ROUTE_OBJECTS:
        return None

    method_name = deco.func.attr.lower()
    if not deco.args:
        return None
    path_node = deco.args[0]
    if not (isinstance(path_node, ast.Constant) and isinstance(path_node.value, str)):
        return None
    path = path_node.value
    if not path.startswith("/"):
        return None

    if method_name in _HTTP_METHODS:
        return (method_name.upper(), path)

    if method_name == "route":
        method = "GET"
        for kw in deco.keywords:
            if kw.arg != "methods":
                continue
            if isinstance(kw.value, ast.List) and kw.value.elts:
                first = kw.value.elts[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    method = first.value.upper()
                    break
        return (method, path)

    return None


# ── Phase 2b: Per-function variable→model tracking & table-op extraction ─────

def _is_db_call(call: ast.Call, method: str) -> bool:
    """True if `call` looks like `db.<method>(...)` (or `session.<method>(...)`)."""
    if not isinstance(call.func, ast.Attribute) or call.func.attr != method:
        return False
    obj = call.func.value
    return isinstance(obj, ast.Name) and obj.id in _ORM_OBJECTS


def _trace_query_model(value: ast.expr, registry: dict[str, str]) -> Optional[str]:
    """
    Walk a chained call expression inward until we hit `db.query(Model)...`.
    Returns the model class name (if registered) or None.

    Handles:
        db.query(Model).filter(...).first()
        db.query(Model).all()
        db.query(Model).filter(...).delete()
    """
    cur = value
    while isinstance(cur, ast.Call):
        if _is_db_call(cur, "query") and cur.args:
            first_arg = cur.args[0]
            if isinstance(first_arg, ast.Name) and first_arg.id in registry:
                return first_arg.id
            return None
        if isinstance(cur.func, ast.Attribute):
            cur = cur.func.value
        else:
            break
    return None


def _resolve_target_model(target: ast.expr,
                          var_models: dict[str, str],
                          registry: dict[str, str]) -> Optional[str]:
    """
    For an Attribute assignment target like `existing.quantity` or
    `item.product.stock_qty`, figure out which model is being mutated.

    Strategy:
      - If the immediate object is itself an Attribute (`item.product.stock_qty`),
        treat the middle attr name (`product`) as a relationship pointing to a
        registered model — match by case-insensitive equality / suffix.
      - Otherwise walk inward to the innermost Name and look it up in
        the per-function var_models map.
    """
    if not isinstance(target, ast.Attribute):
        return None
    obj = target.value

    if isinstance(obj, ast.Attribute):
        attr = obj.attr.lower()
        for model_name in registry:
            ml = model_name.lower()
            if attr == ml or attr.endswith(ml):
                return model_name

    inner = obj
    while isinstance(inner, ast.Attribute):
        inner = inner.value
    if isinstance(inner, ast.Name):
        return var_models.get(inner.id)
    return None


def _extract_tables_from_function(func: ast.FunctionDef,
                                   registry: dict[str, str],
                                   known_tables: Optional[set[str]]) -> list[dict]:
    """Analyse a single route handler and return its table touches."""
    table_ops: dict[str, set[str]] = {}

    def emit(table: Optional[str], op: str):
        if not table:
            return
        t = table.lower().strip()
        if not t:
            return
        if known_tables is not None and t not in known_tables:
            return
        table_ops.setdefault(t, set()).add(op)

    def emit_model(model: Optional[str], op: str):
        if model and model in registry:
            emit(registry[model], op)

    # ── Pass 1: build var_models map ─────────────────────────────────────────
    # Two seeding rules:
    #   var = db.query(Model)...  → var is a Model instance (or queryset)
    #   var = Model(...)          → var is a Model instance (constructor call)
    # Plus loop propagation:
    #   for item in <queried_var>  → item inherits the model
    #   for item in db.query(Model).all()  → item inherits via inline trace
    var_models: dict[str, str] = {}

    for node in ast.walk(func):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if not isinstance(target, ast.Name):
                continue
            # `var = db.query(Model)...`
            model = _trace_query_model(node.value, registry)
            if model:
                var_models[target.id] = model
                continue
            # `var = Model(...)` — direct constructor call on a registered class
            if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name):
                if node.value.func.id in registry:
                    var_models[target.id] = node.value.func.id

        elif isinstance(node, ast.For):
            if not isinstance(node.target, ast.Name):
                continue
            if isinstance(node.iter, ast.Name) and node.iter.id in var_models:
                var_models[node.target.id] = var_models[node.iter.id]
            else:
                model = _trace_query_model(node.iter, registry)
                if model:
                    var_models[node.target.id] = model

    # ── Pass 2: emit table operations ────────────────────────────────────────
    for node in ast.walk(func):

        if isinstance(node, ast.Call) and _is_db_call(node, "query"):
            for arg in node.args:
                if isinstance(arg, ast.Name) and arg.id in registry:
                    emit_model(arg.id, "READ")

        elif isinstance(node, ast.Call) and _is_db_call(node, "add"):
            if node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name):
                    emit_model(arg.func.id, "WRITE")
                elif isinstance(arg, ast.Name) and arg.id in var_models:
                    emit_model(var_models[arg.id], "WRITE")

        elif isinstance(node, ast.Call) and _is_db_call(node, "delete"):
            if node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Name) and arg.id in var_models:
                    emit_model(var_models[arg.id], "WRITE")

        elif isinstance(node, (ast.Assign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if isinstance(t, ast.Attribute):
                    emit_model(_resolve_target_model(t, var_models, registry), "WRITE")

    # ── Raw SQL fallback: scan string args of call expressions ───────────────
    for node in ast.walk(func):
        if not isinstance(node, ast.Call):
            continue
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                _apply_sql_regex(arg.value, emit)

    return [
        {"name": t, "operations": sorted(ops)}
        for t, ops in sorted(table_ops.items())
    ]


def _apply_sql_regex(text: str, emit: Callable[[str, str], None]):
    for pattern, op in _SQL_PATTERNS:
        for m in pattern.finditer(text):
            emit(m.group(1), op)


# ── Phase 2c: Python module → endpoint records ───────────────────────────────

def _parse_python_module(path: Path,
                          registry: dict[str, str],
                          known_tables: Optional[set[str]],
                          rel_root: Path) -> list[dict]:
    try:
        tree = ast.parse(path.read_text(errors="ignore"), filename=str(path))
    except SyntaxError:
        return []

    results: list[dict] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for deco in node.decorator_list:
            route = _parse_route_decorator(deco)
            if not route:
                continue
            method, path_str = route
            tables = _extract_tables_from_function(node, registry, known_tables)
            results.append({
                "endpoint": f"{method} {path_str}",
                "file": str(path.relative_to(rel_root)),
                "tables": tables,
            })
    return results


# ── Phase 3: Node/Express fallback (tree-sitter) ─────────────────────────────

_NODE_PARSER = Parser(Language(tsjs.language()))


def _ts_walk(node: Node):
    stack = [node]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(reversed(n.children))


def _ts_text(node: Node, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _parse_node_file(path: Path,
                      known_tables: Optional[set[str]],
                      rel_root: Path) -> list[dict]:
    src = path.read_bytes()
    root = _NODE_PARSER.parse(src).root_node
    results: list[dict] = []

    for n in _ts_walk(root):
        if n.type != "call_expression":
            continue
        callee = n.child_by_field_name("function")
        if not callee or callee.type != "member_expression":
            continue
        obj = callee.child_by_field_name("object")
        prop = callee.child_by_field_name("property")
        if not obj or not prop:
            continue
        if _ts_text(obj, src) not in _ROUTE_OBJECTS:
            continue
        method = _ts_text(prop, src).lower()
        if method not in _HTTP_METHODS:
            continue
        args = n.child_by_field_name("arguments")
        if not args:
            continue
        path_node = next((c for c in args.children
                          if c.type in ("string", "template_string")), None)
        if not path_node:
            continue
        raw_path = _ts_text(path_node, src)
        if raw_path and raw_path[0] in "\"'`":
            raw_path = raw_path[1:-1]
        if not raw_path.startswith("/"):
            continue

        table_ops: dict[str, set[str]] = {}

        def emit(table: str, op: str):
            t = table.lower().strip()
            if known_tables is not None and t not in known_tables:
                return
            table_ops.setdefault(t, set()).add(op)

        _apply_sql_regex(_ts_text(n, src), emit)

        results.append({
            "endpoint": f"{method.upper()} {raw_path}",
            "file": str(path.relative_to(rel_root)),
            "tables": [{"name": t, "operations": sorted(ops)}
                       for t, ops in sorted(table_ops.items())],
        })
    return results


# ── Main entry ────────────────────────────────────────────────────────────────

def parse_api_dir(api_dir: str,
                  known_tables: Optional[set[str]] = None) -> list[dict]:
    """
    Walk api_dir, build the SQLAlchemy model registry, then extract
    route→table mappings from every Python module and, as a fallback,
    every non-test .js file.
    """
    rel_root = Path(api_dir)
    registry = build_model_registry(api_dir)
    results: list[dict] = []

    for root, _, files in os.walk(api_dir):
        for fname in files:
            path = Path(root) / fname
            if fname.endswith(".py"):
                results.extend(_parse_python_module(path, registry, known_tables, rel_root))
            elif fname.endswith(".js") and "node_modules" not in str(path):
                results.extend(_parse_node_file(path, known_tables, rel_root))

    return results


if __name__ == "__main__":
    import sys
    api_dir = sys.argv[1] if len(sys.argv) > 1 else "../proxy-app/backend"
    print(json.dumps(parse_api_dir(api_dir), indent=2))
