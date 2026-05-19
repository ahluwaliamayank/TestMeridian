"""
dashboard.py
------------
Streamlit dashboard for ImpactMap.

Run:
    streamlit run dashboard.py

The dashboard loads a pre-built graph.json, takes a natural-language test
scenario from the user, calls the existing analyze_scenario() function,
and renders:
  - The dependency graph (UI → API → DB) with touched nodes/edges highlighted
  - The structured analysis (workflow, API sequence, impacted tables, ...)
  - Test data requirements + suggested positive/negative test cases
"""

import json
import os
from pathlib import Path

import streamlit as st

from analyze import analyze_scenario


# ── Styling constants ────────────────────────────────────────────────────────

COMPONENT_ACTIVE = "#1f77b4"   # blue
COMPONENT_DIM    = "#cfd8dc"
ENDPOINT_ACTIVE  = "#f59e0b"   # amber
ENDPOINT_DIM     = "#e0e0e0"
TABLE_ACTIVE     = "#10b981"   # green
TABLE_DIM        = "#e0e0e0"
EDGE_ACTIVE      = "#222"
EDGE_DIM         = "#cccccc"


# ── DOT graph builder ────────────────────────────────────────────────────────

def _q(s: str) -> str:
    """Quote an identifier for DOT, escaping internal quotes."""
    return '"' + s.replace('"', '\\"') + '"'


def build_dot(graph: dict,
              components_touched: set[str],
              endpoints_touched: set[str],
              tables_touched: set[str]) -> str:
    """
    Render the dependency graph as DOT, with touched nodes/edges in strong
    colors and untouched ones dimmed.
    """
    lines: list[str] = [
        "digraph G {",
        '  rankdir=LR;',
        '  bgcolor="white";',
        '  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=11];',
        '  edge [fontname="Helvetica", fontsize=9];',
    ]

    # ── UI cluster ───────────────────────────────────────────────────────────
    lines.append('  subgraph cluster_ui {')
    lines.append('    label="UI"; style="rounded"; color="#bbbbbb"; fontname="Helvetica";')
    for c in graph["components"]:
        active = c["id"] in components_touched
        fill = COMPONENT_ACTIVE if active else COMPONENT_DIM
        fontcolor = "white" if active else "#666"
        lines.append(
            f'    {_q(c["id"])} [fillcolor="{fill}", fontcolor="{fontcolor}"];'
        )
    lines.append('  }')

    # ── API cluster ──────────────────────────────────────────────────────────
    lines.append('  subgraph cluster_api {')
    lines.append('    label="API"; style="rounded"; color="#bbbbbb"; fontname="Helvetica";')
    for ep in graph["endpoints"]:
        active = ep["id"] in endpoints_touched
        fill = ENDPOINT_ACTIVE if active else ENDPOINT_DIM
        fontcolor = "white" if active else "#666"
        lines.append(
            f'    {_q(ep["id"])} [fillcolor="{fill}", fontcolor="{fontcolor}"];'
        )
    lines.append('  }')

    # ── DB cluster ───────────────────────────────────────────────────────────
    lines.append('  subgraph cluster_db {')
    lines.append('    label="DB"; style="rounded"; color="#bbbbbb"; fontname="Helvetica";')
    for t in graph["tables"]:
        active = t["id"] in tables_touched
        fill = TABLE_ACTIVE if active else TABLE_DIM
        fontcolor = "white" if active else "#666"
        lines.append(
            f'    {_q(t["id"])} [shape=cylinder, fillcolor="{fill}", fontcolor="{fontcolor}"];'
        )
    lines.append('  }')

    # ── Edges: component → endpoint ──────────────────────────────────────────
    for e in graph["edges"]["component_to_endpoint"]:
        active = e["from"] in components_touched and e["to"] in endpoints_touched
        color = EDGE_ACTIVE if active else EDGE_DIM
        style = "solid" if active else "dashed"
        penwidth = "2" if active else "1"
        lines.append(
            f'  {_q(e["from"])} -> {_q(e["to"])} '
            f'[color="{color}", style="{style}", penwidth={penwidth}];'
        )

    # ── Edges: endpoint → table ──────────────────────────────────────────────
    for e in graph["edges"]["endpoint_to_table"]:
        active = e["from"] in endpoints_touched and e["to"] in tables_touched
        color = EDGE_ACTIVE if active else EDGE_DIM
        style = "solid" if active else "dashed"
        penwidth = "2" if active else "1"
        ops = "|".join(e.get("operations", []))
        label = f' label="{ops}"' if active and ops else ""
        lines.append(
            f'  {_q(e["from"])} -> {_q(e["to"])} '
            f'[color="{color}", style="{style}", penwidth={penwidth}{label}];'
        )

    lines.append("}")
    return "\n".join(lines)


# ── Result rendering ─────────────────────────────────────────────────────────

def render_analysis(result: dict):
    st.markdown(f"#### Scenario")
    st.write(result.get("scenario_summary", ""))

    # UI workflow
    workflow = result.get("ui_workflow", [])
    if workflow:
        st.markdown("#### UI workflow")
        for step in workflow:
            apis = step.get("triggers_apis", [])
            api_str = " · ".join(f"`{a}`" for a in apis) if apis else ""
            st.markdown(
                f"**{step.get('step', '?')}.** `{step.get('component', '')}` — "
                f"{step.get('action', '')}"
                + (f"  \n&nbsp;&nbsp;&nbsp;&nbsp;↳ {api_str}" if api_str else "")
            )

    # API call sequence
    calls = result.get("api_call_sequence", [])
    if calls:
        st.markdown("#### API call sequence")
        for c in calls:
            ops = c.get("table_operations", [])
            op_str = ", ".join(f"{t['table']} ({t['operation']})" for t in ops)
            st.markdown(
                f"**{c.get('order', '?')}.** `{c.get('endpoint', '')}` "
                f"← `{c.get('triggered_by', '')}`  \n"
                f"&nbsp;&nbsp;&nbsp;&nbsp;{c.get('purpose', '')}"
                + (f"  \n&nbsp;&nbsp;&nbsp;&nbsp;_tables:_ {op_str}" if op_str else "")
            )

    # Impacted tables
    tables = result.get("impacted_tables", [])
    if tables:
        st.markdown("#### Impacted tables")
        for t in tables:
            ops = " · ".join(t.get("operations", []))
            cascades = t.get("cascades_to", [])
            st.markdown(
                f"**`{t.get('table', '')}`** — {ops}  \n"
                f"&nbsp;&nbsp;&nbsp;&nbsp;{t.get('reason', '')}"
                + (
                    f"  \n&nbsp;&nbsp;&nbsp;&nbsp;_cascades to:_ "
                    + ", ".join(f"`{c}`" for c in cascades)
                    if cascades else ""
                )
            )

    # Test data setup
    tdr = result.get("test_data_requirements") or {}
    if tdr:
        st.markdown("#### Test data setup")
        needs = tdr.get("needs_existing_data")
        desc = tdr.get("description", "")
        if needs:
            st.warning(f"**Pre-existing data required.** {desc}")
        else:
            st.success(f"**No pre-existing data needed.** {desc}")

    # Suggested test cases
    cases = result.get("test_cases", [])
    if cases:
        st.markdown("#### Suggested test cases")
        for case in cases:
            ctype = (case.get("type") or "").lower()
            badge = "✓ POSITIVE" if ctype == "positive" else "✗ NEGATIVE"
            title = case.get("title", "")
            with st.expander(f"{badge} · {title}", expanded=(ctype == "positive")):
                st.write(case.get("description", ""))
                td = case.get("test_data", "")
                if td:
                    st.markdown(f"**Data:** {td}")

    # QA checklist
    checklist = result.get("test_checklist", [])
    if checklist:
        st.markdown("#### QA checklist")
        for item in checklist:
            st.checkbox(item, key=f"chk_{hash(item)}")

    # Risk notes
    risk = result.get("risk_notes", "")
    if risk:
        with st.expander("⚠ Risk notes", expanded=False):
            st.write(risk)


# ── Page ──────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="ImpactMap",
    page_icon=None,
    layout="wide",
)

st.title("ImpactMap")
st.caption("Trace a test scenario through UI → API → DB and surface test data requirements + cases.")

# Sidebar: graph + diagnostics
with st.sidebar:
    st.header("Graph")
    default_path = "graph.json"
    graph_path = st.text_input("Path to graph.json", value=default_path)
    graph: dict | None = None
    if Path(graph_path).exists():
        try:
            graph = json.loads(Path(graph_path).read_text())
            st.success(
                f"Loaded **{len(graph['components'])}** components · "
                f"**{len(graph['endpoints'])}** endpoints · "
                f"**{len(graph['tables'])}** tables"
            )
        except json.JSONDecodeError as e:
            st.error(f"Failed to parse {graph_path}: {e}")
    else:
        st.warning(
            f"`{graph_path}` not found.\n\n"
            "Build it first with:\n"
            "```\npython analyze.py --ui … --api … --db-url …\n```"
        )

    st.markdown("---")
    st.header("Anthropic API key")
    env_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if env_key:
        st.success("Using key from `ANTHROPIC_API_KEY` env var.")
        api_key = env_key
    else:
        api_key = st.text_input(
            "Paste your key",
            type="password",
            help="Used only in this session; not persisted. "
                 "Alternatively export ANTHROPIC_API_KEY before launching Streamlit.",
        )

# Main: scenario input + result
if graph is None:
    st.stop()

if "result" not in st.session_state:
    st.session_state["result"] = None
    st.session_state["scenario"] = ""

scenario = st.text_area(
    "Test scenario",
    placeholder="e.g. User searches for headphones, adds to cart, and places an order",
    height=100,
    key="scenario_input",
)

col_btn, col_clear, _ = st.columns([1, 1, 6])
with col_btn:
    analyze_clicked = st.button("Analyze", type="primary", use_container_width=True)
with col_clear:
    if st.button("Clear", use_container_width=True):
        st.session_state["result"] = None

if analyze_clicked:
    if not scenario.strip():
        st.warning("Enter a scenario first.")
    elif not api_key:
        st.error("No Anthropic API key — paste one in the sidebar or set `ANTHROPIC_API_KEY` in your shell.")
    else:
        # Make the key available to analyze_scenario(), which reads it from env.
        os.environ["ANTHROPIC_API_KEY"] = api_key
        with st.spinner("Calling Claude…"):
            try:
                st.session_state["result"] = analyze_scenario(graph, scenario)
                st.session_state["scenario"] = scenario
            except SystemExit as e:
                # analyze_scenario calls sys.exit on JSON parse failures
                st.error("Claude returned a response that couldn't be parsed as JSON. Try a more specific scenario.")
                st.session_state["result"] = None
            except Exception as e:
                st.error(f"Analysis failed: {e}")
                st.session_state["result"] = None

result = st.session_state["result"]

if result is not None:
    # Extract highlight sets
    components_touched = {s.get("component", "") for s in result.get("ui_workflow", [])}
    endpoints_touched  = {c.get("endpoint", "")  for c in result.get("api_call_sequence", [])}
    tables_touched     = {t.get("table", "")     for t in result.get("impacted_tables", [])}

    # Surface any names the LLM mentioned that aren't in the graph
    known_components = {c["id"] for c in graph["components"]}
    known_endpoints  = {e["id"] for e in graph["endpoints"]}
    known_tables     = {t["id"] for t in graph["tables"]}
    unknown = (
        [c for c in components_touched if c and c not in known_components]
        + [e for e in endpoints_touched if e and e not in known_endpoints]
        + [t for t in tables_touched     if t and t not in known_tables]
    )
    if unknown:
        st.info(
            "The model referenced names not present in the graph (will not be highlighted): "
            + ", ".join(f"`{u}`" for u in unknown)
        )

    st.markdown("### Dependency graph")
    dot = build_dot(
        graph,
        components_touched & known_components,
        endpoints_touched & known_endpoints,
        tables_touched & known_tables,
    )
    st.graphviz_chart(dot, use_container_width=True)

    st.markdown("### Analysis")
    render_analysis(result)
