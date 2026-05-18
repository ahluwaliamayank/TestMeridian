"""
build_graph.py
--------------
Assembles the three parsed outputs into a single graph:

  graph.json structure:
  {
    "components": [ { "id", "file", "api_calls": ["METHOD /path"] } ],
    "endpoints":  [ { "id", "file", "tables": [{"name","operations"}] } ],
    "tables":     [ { "id", "columns", "foreign_keys" } ],
    "edges": {
      "component_to_endpoint": [ {"from": component_id, "to": endpoint_id} ],
      "endpoint_to_table":     [ {"from": endpoint_id,  "to": table_name, "operations": [...]} ]
    }
  }
"""

import json
from pathlib import Path

from parse_ui import parse_ui_dir
from parse_api import parse_api_dir
from introspect_db import introspect


def build_graph(ui_dir: str, api_dir: str, db_url: str) -> dict:
    print(f"  Parsing UI:       {ui_dir}")
    ui_components = parse_ui_dir(ui_dir)
    print(f"  -> {len(ui_components)} components found")

    print(f"  Introspecting DB: {db_url}")
    schema_tables = introspect(db_url)
    known_tables = {t["table"] for t in schema_tables}
    print(f"  -> {len(schema_tables)} tables found: {sorted(known_tables)}")

    print(f"  Parsing API:      {api_dir}")
    api_endpoints = parse_api_dir(api_dir, known_tables)
    print(f"  -> {len(api_endpoints)} endpoints found")

    # Normalise endpoint IDs
    endpoint_ids = {ep["endpoint"] for ep in api_endpoints}

    # Edges: component -> endpoint
    comp_to_ep_edges = []
    for comp in ui_components:
        for api_call in comp["api_calls"]:
            if api_call in endpoint_ids:
                comp_to_ep_edges.append({"from": comp["component"], "to": api_call})
            else:
                call_path = api_call.split(" ", 1)[-1] if " " in api_call else api_call
                for ep_id in endpoint_ids:
                    ep_path = ep_id.split(" ", 1)[-1] if " " in ep_id else ep_id
                    if call_path == ep_path or call_path.rstrip("/") == ep_path.rstrip("/"):
                        comp_to_ep_edges.append({"from": comp["component"], "to": ep_id})
                        break

    # Edges: endpoint -> table
    ep_to_table_edges = []
    for ep in api_endpoints:
        for t in ep["tables"]:
            ep_to_table_edges.append({
                "from": ep["endpoint"],
                "to": t["name"],
                "operations": t["operations"],
            })

    graph = {
        "components": [
            {"id": c["component"], "file": c["file"], "api_calls": c["api_calls"]}
            for c in ui_components
        ],
        "endpoints": [
            {"id": ep["endpoint"], "file": ep["file"], "tables": ep["tables"]}
            for ep in api_endpoints
        ],
        "tables": [
            {"id": t["table"], "columns": t["columns"], "foreign_keys": t["foreign_keys"]}
            for t in schema_tables
        ],
        "edges": {
            "component_to_endpoint": comp_to_ep_edges,
            "endpoint_to_table": ep_to_table_edges,
        },
    }

    return graph


def save_graph(graph: dict, output_path: str = "graph.json"):
    Path(output_path).write_text(json.dumps(graph, indent=2))
    print(f"\n  Graph saved -> {output_path}")
    print(f"  Summary: {len(graph['components'])} components, "
          f"{len(graph['endpoints'])} endpoints, "
          f"{len(graph['tables'])} tables, "
          f"{len(graph['edges']['component_to_endpoint'])} UI->API edges, "
          f"{len(graph['edges']['endpoint_to_table'])} API->Table edges")


if __name__ == "__main__":
    import sys, os
    ui_dir  = sys.argv[1] if len(sys.argv) > 1 else "../proxy-app/frontend/src"
    api_dir = sys.argv[2] if len(sys.argv) > 2 else "../proxy-app/backend"
    db_url  = sys.argv[3] if len(sys.argv) > 3 else os.environ.get(
        "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/impactmap"
    )
    out     = sys.argv[4] if len(sys.argv) > 4 else "graph.json"
    graph = build_graph(ui_dir, api_dir, db_url)
    save_graph(graph, out)
