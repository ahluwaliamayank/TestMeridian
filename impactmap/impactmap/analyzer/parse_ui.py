"""
parse_ui.py
-----------
AST-based parser for React/JSX/TSX components using tree-sitter.

For each source file, parses to an AST and:
  1. Collects every top-level PascalCase component declaration
     (`function Name`, `const Name = () =>`, optionally `export [default]`)
  2. For each component, scans *its own body subtree* for API calls via:
       - Imported wrapper functions (resolved through api/client.js)
       - Direct `axios.METHOD("/...")` / `api.METHOD("/...")` calls
       - Raw `fetch("/...", { method: "POST" })` (method is inferred from
         the options object, not hard-coded to GET)
  3. Emits one record per component that actually touches the backend.

Output: list of dicts
  { "component": str, "file": str, "api_calls": [str, ...] }
"""

import os
import re
import json
from pathlib import Path
from typing import Optional

import tree_sitter_javascript as tsjs
import tree_sitter_typescript as tsts
from tree_sitter import Language, Node, Parser


# ── Parsers per file extension ───────────────────────────────────────────────

_JS = Language(tsjs.language())
_TS = Language(tsts.language_typescript())
_TSX = Language(tsts.language_tsx())

_PARSERS: dict[str, Parser] = {
    ".js":  Parser(_JS),
    ".jsx": Parser(_JS),   # tree-sitter-javascript handles JSX natively
    ".ts":  Parser(_TS),
    ".tsx": Parser(_TSX),
}

_TEMPLATE_SUB_RE = re.compile(r"\$\{[^}]*\}")
_HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}
_SKIP_FILES = {"client.js", "client.ts", "client.jsx", "client.tsx"}


# ── Small AST helpers ────────────────────────────────────────────────────────

def _parse_file(path: Path) -> Optional[tuple[Node, bytes]]:
    parser = _PARSERS.get(path.suffix.lower())
    if parser is None:
        return None
    src = path.read_bytes()
    return parser.parse(src).root_node, src


def _text(node: Node, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _strip_quotes(s: str) -> str:
    return s[1:-1] if s and s[0] in "\"'`" else s


def _normalize_path(raw_with_quotes: str) -> str:
    return _TEMPLATE_SUB_RE.sub(":param", _strip_quotes(raw_with_quotes))


def _is_pascal(name: str) -> bool:
    return bool(name) and name[0].isupper()


def _walk(node: Node):
    """Depth-first pre-order traversal yielding `node` and every descendant."""
    stack = [node]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(reversed(n.children))


def _first_string_arg(call: Node) -> Optional[Node]:
    args = call.child_by_field_name("arguments")
    if not args:
        return None
    for c in args.children:
        if c.type in ("string", "template_string"):
            return c
    return None


# ── 1. Build the api/client.js export map ────────────────────────────────────

def parse_api_client(ui_dir: str) -> dict[str, str]:
    """
    Locate client.js / client.ts under `ui_dir` and return
        { exported_function_name: "METHOD /path" }
    """
    mapping: dict[str, str] = {}
    for root, _, files in os.walk(ui_dir):
        for fname in files:
            if fname not in _SKIP_FILES:
                continue
            parsed = _parse_file(Path(root) / fname)
            if parsed is None:
                continue
            root_node, src = parsed
            mapping.update(_extract_client_exports(root_node, src))
    return mapping


def _extract_client_exports(root: Node, src: bytes) -> dict[str, str]:
    """
    Find `export const NAME = (...) => api.METHOD("path", ...)` shapes.
    Returns {NAME: "METHOD /path"}.
    """
    out: dict[str, str] = {}
    for node in _walk(root):
        if node.type != "export_statement":
            continue
        decl = next((c for c in node.children if c.type == "lexical_declaration"), None)
        if decl is None:
            continue
        for declarator in decl.children:
            if declarator.type != "variable_declarator":
                continue
            name_node = declarator.child_by_field_name("name")
            value_node = declarator.child_by_field_name("value")
            if not name_node or not value_node:
                continue
            call = _first_http_call(value_node, src)
            if call:
                out[_text(name_node, src)] = call
    return out


def _first_http_call(scope: Node, src: bytes) -> Optional[str]:
    """First `api.METHOD("...")` / `axios.METHOD("...")` inside `scope`."""
    for n in _walk(scope):
        if n.type != "call_expression":
            continue
        callee = n.child_by_field_name("function")
        if not callee or callee.type != "member_expression":
            continue
        obj = callee.child_by_field_name("object")
        prop = callee.child_by_field_name("property")
        if not obj or not prop:
            continue
        if _text(obj, src) not in ("api", "axios"):
            continue
        method = _text(prop, src).lower()
        if method not in _HTTP_METHODS:
            continue
        arg = _first_string_arg(n)
        if arg is None:
            continue
        path = _normalize_path(_text(arg, src))
        return f"{method.upper()} /{path.lstrip('/')}"
    return None


# ── 2. Per-file component & call extraction ──────────────────────────────────

def _client_imports(root: Node, src: bytes) -> set[str]:
    """Identifiers imported from a module path ending in 'client'."""
    imported: set[str] = set()
    for node in _walk(root):
        if node.type != "import_statement":
            continue
        source = node.child_by_field_name("source")
        if source is None:
            continue
        source_text = _strip_quotes(_text(source, src))
        if not (source_text.endswith("/client") or source_text == "client"):
            continue
        for n in _walk(node):
            if n.type == "import_specifier":
                name_node = n.child_by_field_name("name")
                if name_node:
                    imported.add(_text(name_node, src))
    return imported


def _top_level_components(root: Node, src: bytes) -> list[tuple[str, Node]]:
    """
    Return [(name, body_node), ...] for every PascalCase top-level component.

    Handles:
        function Name() {...}
        const Name = () => {...}
        const Name = function () {...}
        export [default] function Name() {...}
        export [default] const Name = () => {...}
    """
    out: list[tuple[str, Node]] = []

    for child in root.children:
        target = child
        if child.type == "export_statement":
            inner = next(
                (c for c in child.children
                 if c.type in ("function_declaration",
                               "lexical_declaration",
                               "variable_declaration")),
                None,
            )
            if inner is not None:
                target = inner

        if target.type == "function_declaration":
            name_node = target.child_by_field_name("name")
            body = target.child_by_field_name("body")
            if name_node and body and _is_pascal(_text(name_node, src)):
                out.append((_text(name_node, src), body))

        elif target.type in ("lexical_declaration", "variable_declaration"):
            for declarator in target.children:
                if declarator.type != "variable_declarator":
                    continue
                name_node = declarator.child_by_field_name("name")
                value_node = declarator.child_by_field_name("value")
                if not name_node or not value_node:
                    continue
                name = _text(name_node, src)
                if not _is_pascal(name):
                    continue
                if value_node.type in ("arrow_function", "function_expression"):
                    body = value_node.child_by_field_name("body") or value_node
                    out.append((name, body))

    return out


def _api_calls_in_scope(scope: Node, src: bytes,
                        client_map: dict[str, str],
                        client_imports: set[str]) -> set[str]:
    """Collect "METHOD /path" strings reached from within `scope`."""
    calls: set[str] = set()
    for n in _walk(scope):
        if n.type != "call_expression":
            continue
        callee = n.child_by_field_name("function")
        if callee is None:
            continue

        if callee.type == "identifier":
            name = _text(callee, src)
            if name in client_imports and name in client_map:
                calls.add(client_map[name])
            elif name == "fetch":
                resolved = _parse_fetch_call(n, src)
                if resolved:
                    calls.add(resolved)

        elif callee.type == "member_expression":
            obj = callee.child_by_field_name("object")
            prop = callee.child_by_field_name("property")
            if not obj or not prop:
                continue
            if _text(obj, src) not in ("api", "axios"):
                continue
            method = _text(prop, src).lower()
            if method not in _HTTP_METHODS:
                continue
            arg = _first_string_arg(n)
            if arg is None:
                continue
            path = _normalize_path(_text(arg, src))
            if path.startswith("/") or path.startswith("http"):
                calls.add(f"{method.upper()} /{path.lstrip('/')}")

    return calls


def _parse_fetch_call(call: Node, src: bytes) -> Optional[str]:
    """
    `fetch(url)` → "GET /url"
    `fetch(url, { method: "POST" })` → "POST /url"
    Returns None if the URL isn't a literal we can normalize.
    """
    args = call.child_by_field_name("arguments")
    if not args:
        return None
    named = [c for c in args.children if c.is_named]
    if not named:
        return None
    if named[0].type not in ("string", "template_string"):
        return None
    path = _normalize_path(_text(named[0], src))
    if not (path.startswith("/") or path.startswith("http")):
        return None

    method = "GET"
    if len(named) >= 2 and named[1].type == "object":
        for prop in named[1].children:
            if prop.type != "pair":
                continue
            key = prop.child_by_field_name("key")
            value = prop.child_by_field_name("value")
            if not key or not value:
                continue
            key_text = _strip_quotes(_text(key, src))
            if key_text.lower() == "method" and value.type in ("string", "template_string"):
                method = _strip_quotes(_text(value, src)).upper()
                break

    return f"{method} /{path.lstrip('/')}"


# ── 3. Driver ────────────────────────────────────────────────────────────────

def parse_ui_dir(ui_dir: str) -> list[dict]:
    client_map = parse_api_client(ui_dir)
    results: list[dict] = []

    for root, _, files in os.walk(ui_dir):
        for fname in files:
            ext = Path(fname).suffix.lower()
            if ext not in _PARSERS:
                continue
            if fname in _SKIP_FILES or "test" in fname.lower() or fname.startswith("vite"):
                continue

            path = Path(root) / fname
            parsed = _parse_file(path)
            if parsed is None:
                continue
            root_node, src = parsed

            imports = _client_imports(root_node, src)
            for name, body in _top_level_components(root_node, src):
                calls = _api_calls_in_scope(body, src, client_map, imports)
                if not calls:
                    continue
                results.append({
                    "component": name,
                    "file": str(path.relative_to(ui_dir)),
                    "api_calls": sorted(calls),
                })

    return results


if __name__ == "__main__":
    import sys
    ui_dir = sys.argv[1] if len(sys.argv) > 1 else "proxy-app/frontend/src"
    print(json.dumps(parse_ui_dir(ui_dir), indent=2))
