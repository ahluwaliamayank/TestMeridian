"""
parse_ui.py
-----------
Parses a React (JSX/TSX/JS) source directory and extracts:
  - Component name  (from filename or function/class declaration)
  - API calls made  (from import usage of the api/client.js functions,
                     or direct fetch/axios calls with URL strings)

Output: list of dicts
  { "component": str, "file": str, "api_calls": [str, ...] }

Strategy (PoC-grade, handles the proxy app and most real projects):
  1. Find api/client.js (or client.ts) and build a map of
     export_name → "METHOD /path"
  2. Walk all .jsx/.tsx/.js/.ts files
  3. For each file:
     a. Detect which client exports are imported
     b. Find usages of those imports in the file body → record the API call
     c. Also regex-scan for raw fetch/axios("…") patterns as fallback
"""

import os
import re
import json
from pathlib import Path


# ── Step 1: Parse client.js export map ───────────────────────────────────────

CLIENT_EXPORT_RE = re.compile(
    r'export\s+const\s+(\w+)\s*=.*?api\.(get|post|put|patch|delete|GET|POST|PUT|PATCH|DELETE)\s*\(\s*[`\'"](.*?)[`\'"]',
    re.IGNORECASE | re.DOTALL,
)

def parse_api_client(ui_dir: str) -> dict[str, str]:
    """
    Find client.js / client.ts under ui_dir and return
    { function_name: "METHOD /path" }
    """
    mapping = {}
    for root, _, files in os.walk(ui_dir):
        for fname in files:
            if fname in ("client.js", "client.ts"):
                path = Path(root) / fname
                text = path.read_text(errors="ignore")
                for m in CLIENT_EXPORT_RE.finditer(text):
                    fn_name, method, path_str = m.group(1), m.group(2).upper(), m.group(3)
                    # Normalise template literals that have ${…} – keep the static prefix
                    path_str = re.sub(r'\$\{.*?\}', ':param', path_str)
                    mapping[fn_name] = f"{method} /{path_str.lstrip('/')}"
    return mapping


# ── Step 2: Walk component files ─────────────────────────────────────────────

IMPORT_RE = re.compile(
    r'import\s*\{([^}]+)\}\s*from\s*[\'"].*?client[\'"]'
)
FUNCTION_COMPONENT_RE = re.compile(
    r'(?:export\s+(?:default\s+)?)?function\s+([A-Z][A-Za-z0-9_]*)\s*\('
)
ARROW_COMPONENT_RE = re.compile(
    r'(?:export\s+(?:default\s+)?)?(?:const|let)\s+([A-Z][A-Za-z0-9_]*)\s*='
)
# Raw fetch/axios fallback
RAW_FETCH_RE = re.compile(
    r'(?:fetch|axios\.(?:get|post|put|patch|delete))\s*\(\s*[`\'"](.*?)[`\'"]',
    re.IGNORECASE,
)
RAW_AXIOS_BASE_RE = re.compile(
    r'api\.(?P<method>get|post|put|patch|delete)\s*\(\s*[`\'"](/[^\'"`]*)[`\'"]',
    re.IGNORECASE,
)


def _component_name_from_file(filepath: str) -> str:
    stem = Path(filepath).stem
    # PascalCase the stem if needed
    return stem[0].upper() + stem[1:] if stem else "Unknown"


def parse_ui_dir(ui_dir: str) -> list[dict]:
    client_map = parse_api_client(ui_dir)
    results = []

    for root, _, files in os.walk(ui_dir):
        for fname in files:
            if not fname.endswith((".jsx", ".tsx", ".js", ".ts")):
                continue
            # Skip the client itself, test files, config files
            if fname in ("client.js", "client.ts") or "test" in fname.lower() or fname.startswith("vite"):
                continue

            filepath = Path(root) / fname
            text = filepath.read_text(errors="ignore")

            # Detect imported client functions
            imported_fns: list[str] = []
            for m in IMPORT_RE.finditer(text):
                names = [n.strip() for n in m.group(1).split(",")]
                imported_fns.extend(names)

            # Find API calls via imported function usage
            api_calls = set()
            for fn in imported_fns:
                if fn in client_map:
                    # Check the function is actually called (not just imported)
                    if re.search(rf'\b{re.escape(fn)}\s*\(', text):
                        api_calls.add(client_map[fn])

            # Fallback: raw fetch/axios patterns
            for m in RAW_FETCH_RE.finditer(text):
                url = m.group(1)
                if url.startswith("/") or url.startswith("http"):
                    api_calls.add(f"GET {url}")  # method unknown without more context

            for m in RAW_AXIOS_BASE_RE.finditer(text):
                api_calls.add(f"{m.group('method').upper()} {m.group(2)}")

            if not api_calls:
                continue  # Not a component that makes API calls — skip

            # Detect component name
            component = None
            for m in FUNCTION_COMPONENT_RE.finditer(text):
                component = m.group(1)
                break
            if not component:
                for m in ARROW_COMPONENT_RE.finditer(text):
                    component = m.group(1)
                    break
            if not component:
                component = _component_name_from_file(str(filepath))

            results.append({
                "component": component,
                "file": str(filepath.relative_to(ui_dir)),
                "api_calls": sorted(api_calls),
            })

    return results


if __name__ == "__main__":
    import sys
    ui_dir = sys.argv[1] if len(sys.argv) > 1 else "proxy-app/frontend/src"
    data = parse_ui_dir(ui_dir)
    print(json.dumps(data, indent=2))
