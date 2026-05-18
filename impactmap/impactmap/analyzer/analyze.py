"""
analyze.py
----------
Main CLI entrypoint for ImpactMap.

Usage:
  # Build graph from repos and run a scenario in one shot:
  python analyze.py \
    --ui   ../proxy-app/frontend/src \
    --api  ../proxy-app/backend \
    --schema ../proxy-app/schema.sql \
    --scenario "User searches for headphones, adds to cart, and places order"

  # Use a pre-built graph:
  python analyze.py \
    --graph graph.json \
    --scenario "User views order history"

  # Interactive mode (prompts for scenario):
  python analyze.py --graph graph.json

Output:
  - Pretty-printed terminal output with ASCII dependency trace
  - Optional JSON output (--json)
  - Optional save to file (--output result.json)
"""

import argparse
import json
import os
import sys
import textwrap
from pathlib import Path

import anthropic

from build_graph import build_graph, save_graph


# ── Terminal colours ──────────────────────────────────────────────────────────

class C:
    RESET  = "\033[0m"
    BOLD   = "\033[1m"
    DIM    = "\033[2m"
    PURPLE = "\033[35m"
    CYAN   = "\033[36m"
    GREEN  = "\033[32m"
    YELLOW = "\033[33m"
    RED    = "\033[31m"
    WHITE  = "\033[37m"
    BG_DARK = "\033[40m"

def bold(s): return f"{C.BOLD}{s}{C.RESET}"
def dim(s):  return f"{C.DIM}{s}{C.RESET}"
def purple(s): return f"{C.PURPLE}{s}{C.RESET}"
def cyan(s):   return f"{C.CYAN}{s}{C.RESET}"
def green(s):  return f"{C.GREEN}{s}{C.RESET}"
def yellow(s): return f"{C.YELLOW}{s}{C.RESET}"
def red(s):    return f"{C.RED}{s}{C.RESET}"


# ── Graph → LLM prompt ───────────────────────────────────────────────────────

def graph_to_prompt(graph: dict) -> str:
    lines = ["You are an expert in web application architecture and testing."]
    lines.append("\n## APPLICATION DEPENDENCY GRAPH\n")

    lines.append("### UI Components and their API calls")
    for c in graph["components"]:
        lines.append(f"- {c['id']} (file: {c['file']}) → calls: {', '.join(c['api_calls']) or 'none'}")

    lines.append("\n### API Endpoints and their database table operations")
    for ep in graph["endpoints"]:
        table_str = ", ".join(
            f"{t['name']}({'|'.join(t['operations'])})" for t in ep["tables"]
        ) or "none"
        lines.append(f"- {ep['id']} (file: {ep['file']}) → tables: {table_str}")

    lines.append("\n### Database Tables")
    for t in graph["tables"]:
        fks = ", ".join(
            f"{fk['column']}→{fk['references_table']}.{fk['references_column']}"
            for fk in t["foreign_keys"]
        )
        col_names = ", ".join(c["name"] for c in t["columns"])
        lines.append(f"- {t['id']}: [{col_names}]" + (f"  FK: {fks}" if fks else ""))

    lines.append("\n### Dependency edges (UI → API)")
    for e in graph["edges"]["component_to_endpoint"]:
        lines.append(f"- {e['from']} → {e['to']}")

    lines.append("\n### Dependency edges (API → Table)")
    for e in graph["edges"]["endpoint_to_table"]:
        lines.append(f"- {e['from']} → {e['to']} [{', '.join(e['operations'])}]")

    lines.append("""
## YOUR TASK

Given a test scenario in natural language, analyze the dependency graph above and respond ONLY with a valid JSON object (no markdown fences, no explanation outside JSON) with this exact structure:

{
  "scenario_summary": "1-2 sentence restatement of what is being tested",
  "ui_workflow": [
    {
      "step": 1,
      "component": "ComponentName",
      "action": "What the user does at this component",
      "triggers_apis": ["METHOD /path"]
    }
  ],
  "api_call_sequence": [
    {
      "order": 1,
      "endpoint": "METHOD /path",
      "triggered_by": "ComponentName",
      "purpose": "Why this API is called",
      "table_operations": [{"table": "name", "operation": "READ|WRITE"}]
    }
  ],
  "impacted_tables": [
    {
      "table": "table_name",
      "operations": ["READ", "WRITE"],
      "reason": "Explanation of why and how this table is touched",
      "cascades_to": ["other_table"]
    }
  ],
  "test_checklist": [
    "Specific thing a QA engineer should verify for this scenario"
  ],
  "risk_notes": "Side effects, race conditions, cascading deletes, or edge cases a tester should watch for"
}
""")
    return "\n".join(lines)


# ── LLM call ─────────────────────────────────────────────────────────────────

def analyze_scenario(graph: dict, scenario: str) -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print(red("Error: ANTHROPIC_API_KEY environment variable not set."))
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    system_prompt = graph_to_prompt(graph)

    print(dim("\n  Calling Claude..."), end="", flush=True)
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2000,
        system=system_prompt,
        messages=[{"role": "user", "content": f"Test scenario: {scenario}"}],
    )
    print(dim(" done.\n"))

    raw = message.content[0].text.strip()
    # Strip any accidental markdown fences
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(red(f"  Failed to parse LLM response as JSON: {e}"))
        print(dim(raw[:500]))
        sys.exit(1)


# ── Pretty printer ────────────────────────────────────────────────────────────

def print_analysis(result: dict, graph: dict):
    W = 72
    line = "─" * W

    print(f"\n{bold(purple('━' * W))}")
    print(bold(purple("  IMPACTMAP ANALYSIS")))
    print(bold(purple('━' * W)))

    print(f"\n{bold('SCENARIO')}")
    print(textwrap.fill(result.get("scenario_summary", ""), width=W, initial_indent="  ", subsequent_indent="  "))

    # ── UI Workflow ───────────────────────────────────────────────────────────
    print(f"\n{bold(cyan('UI WORKFLOW'))}")
    print(dim(f"  {'Step':<5} {'Component':<25} Action"))
    print(dim(f"  {line[:65]}"))
    for step in result.get("ui_workflow", []):
        num    = str(step["step"])
        comp   = step["component"]
        action = step["action"]
        apis   = step.get("triggers_apis", [])
        print(f"  {cyan(num):<12} {bold(comp):<33} {action}")
        if apis:
            for api in apis:
                method = api.split()[0] if " " in api else "?"
                col = yellow if method in ("POST","PUT","PATCH") else (red if method == "DELETE" else cyan)
                print(f"  {'':5} {'':25} {dim('↳')} {col(api)}")

    # ── API Call Sequence ─────────────────────────────────────────────────────
    print(f"\n{bold(yellow('API CALL SEQUENCE'))}")
    for call in result.get("api_call_sequence", []):
        method_color = (yellow if "POST" in call["endpoint"] or "PUT" in call["endpoint"]
                        else red if "DELETE" in call["endpoint"] else cyan)
        print(f"  {dim(str(call['order']) + '.'):<6} {method_color(bold(call['endpoint']))}")
        print(f"  {'':6} {dim('← ' + call['triggered_by'])}")
        print(f"  {'':6} {call['purpose']}")
        for top in call.get("table_operations", []):
            op_color = yellow if top["operation"] == "WRITE" else green
            print(f"  {'':6} {dim('  ├─')} {op_color(top['operation']):<12} {top['table']}")
        print()

    # ── Impacted Tables (ASCII graph) ─────────────────────────────────────────
    print(f"{bold(green('IMPACTED TABLES'))}")
    tables = result.get("impacted_tables", [])
    schema_table_map = {t["id"]: t for t in graph.get("tables", [])}

    for i, t in enumerate(tables):
        is_last = i == len(tables) - 1
        connector = "└─" if is_last else "├─"
        ops = t.get("operations", [])
        op_badges = " ".join(
            (yellow("WRITE") if op == "WRITE" else green("READ")) for op in ops
        )
        print(f"  {dim(connector)} {bold(green(t['table']))}  {op_badges}")
        print(f"  {'   ' if is_last else dim('│  ')}   {dim(t['reason'])}")

        # Show columns from schema
        schema_t = schema_table_map.get(t["table"])
        if schema_t:
            cols = [c["name"] for c in schema_t["columns"]]
            print(f"  {'   ' if is_last else dim('│  ')}   {dim('cols: ' + ', '.join(cols))}")

        # Cascades
        cascades = t.get("cascades_to", [])
        if cascades:
            for c_table in cascades:
                print(f"  {'   ' if is_last else dim('│  ')}   {dim('↳ cascades to: ')}{yellow(c_table)}")

    # ── Test Checklist ────────────────────────────────────────────────────────
    checklist = result.get("test_checklist", [])
    if checklist:
        print(f"\n{bold('QA CHECKLIST')}")
        for item in checklist:
            print(f"  {green('□')} {item}")

    # ── Risk Notes ────────────────────────────────────────────────────────────
    risk = result.get("risk_notes", "")
    if risk:
        print(f"\n{bold(yellow('⚠  RISK NOTES'))}")
        print(textwrap.fill(risk, width=W, initial_indent="  ", subsequent_indent="  "))

    print(f"\n{bold(purple('━' * W))}\n")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="ImpactMap: trace a test scenario through UI → API → DB",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
        Examples:
          # One-shot: build graph and analyze
          python analyze.py \\
            --ui   ../proxy-app/frontend/src \\
            --api  ../proxy-app/backend \\
            --schema ../proxy-app/schema.sql \\
            --scenario "User adds headphones to cart and checks out"

          # Use pre-built graph
          python analyze.py --graph graph.json \\
            --scenario "User removes an item from cart"

          # Interactive
          python analyze.py --graph graph.json
        """),
    )
    parser.add_argument("--ui",       help="Path to React/UI source directory")
    parser.add_argument("--api",      help="Path to API source directory")
    parser.add_argument("--db-url",   help="Postgres connection string, e.g. postgresql://user:pass@host/db (or set DATABASE_URL env var)")
    parser.add_argument("--graph",    help="Path to pre-built graph.json (skips parsing)")
    parser.add_argument("--scenario", help="Test scenario in natural language")
    parser.add_argument("--save-graph", metavar="PATH", help="Save the built graph to this path")
    parser.add_argument("--output",   metavar="PATH", help="Save analysis result JSON to this path")
    parser.add_argument("--json",     action="store_true", help="Print raw JSON result instead of pretty output")

    args = parser.parse_args()

    # ── Load or build graph ───────────────────────────────────────────────────
    if args.graph:
        print(f"{dim('Loading graph from')} {args.graph}")
        graph = json.loads(Path(args.graph).read_text())
    elif args.ui and args.api:
        import os
        db_url = getattr(args, 'db_url', None) or os.environ.get("DATABASE_URL")
        if not db_url:
            parser.error("Provide --db-url or set DATABASE_URL env var")
        print(f"\n{bold('Building dependency graph...')}")
        graph = build_graph(args.ui, args.api, db_url)
        save_path = args.save_graph or "graph.json"
        save_graph(graph, save_path)
    else:
        parser.error("Provide either --graph OR both --ui and --api (with --db-url or DATABASE_URL)")

    # ── Get scenario ──────────────────────────────────────────────────────────
    scenario = args.scenario
    if not scenario:
        print(f"\n{bold('Available components:')} " +
              ", ".join(c["id"] for c in graph["components"]))
        print(f"{bold('Available endpoints:')}  " +
              ", ".join(ep["id"] for ep in graph["endpoints"]))
        print(f"{bold('Tables:')}               " +
              ", ".join(t["id"] for t in graph["tables"]))
        print()
        scenario = input(bold("Enter test scenario: ")).strip()
        if not scenario:
            print(red("No scenario provided."))
            sys.exit(1)

    # ── Analyze ───────────────────────────────────────────────────────────────
    print(f"\n{bold('Analyzing scenario:')} {cyan(scenario)}")
    result = analyze_scenario(graph, scenario)

    # ── Output ────────────────────────────────────────────────────────────────
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print_analysis(result, graph)

    if args.output:
        Path(args.output).write_text(json.dumps(result, indent=2))
        print(dim(f"Result saved → {args.output}"))


if __name__ == "__main__":
    main()
