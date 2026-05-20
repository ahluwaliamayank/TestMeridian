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

import hashlib
import json
import os
from pathlib import Path

import streamlit as st

from analyze import analyze_scenario, analyze_system, find_scenarios_touching


# ── System-overview disk cache ───────────────────────────────────────────────

_OVERVIEW_CACHE = Path(".system_overview_cache.json")


def _graph_hash(graph: dict) -> str:
    return hashlib.sha256(json.dumps(graph, sort_keys=True).encode()).hexdigest()


def load_system_overview(graph: dict, force: bool = False) -> dict:
    """Reuse a cached overview when the graph hash matches; otherwise call the LLM."""
    h = _graph_hash(graph)
    if not force and _OVERVIEW_CACHE.exists():
        try:
            cached = json.loads(_OVERVIEW_CACHE.read_text())
            if cached.get("hash") == h:
                return cached["result"]
        except (json.JSONDecodeError, KeyError):
            pass
    result = analyze_system(graph)
    _OVERVIEW_CACHE.write_text(json.dumps({"hash": h, "result": result}, indent=2))
    return result


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


def render_full_result(graph: dict, result: dict):
    """Render highlighted graph + structured analysis for one scenario result."""
    components_touched = {s.get("component", "") for s in result.get("ui_workflow", [])}
    endpoints_touched  = {c.get("endpoint", "")  for c in result.get("api_call_sequence", [])}
    tables_touched     = {t.get("table", "")     for t in result.get("impacted_tables", [])}

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

    st.markdown("#### Dependency graph")
    dot = build_dot(
        graph,
        components_touched & known_components,
        endpoints_touched & known_endpoints,
        tables_touched & known_tables,
    )
    st.graphviz_chart(dot, use_container_width=True)

    st.markdown("#### Analysis")
    render_analysis(result)


def render_system_overview(overview: dict):
    summary = overview.get("system_summary", "")
    if summary:
        st.markdown("#### What this system does")
        st.write(summary)

    areas = overview.get("feature_areas", [])
    if not areas:
        st.info("No feature areas returned.")
        return

    for i, area in enumerate(areas):
        st.markdown(f"### {area.get('name', 'Unnamed area')}")
        desc = area.get("description", "")
        if desc:
            st.write(desc)

        comps = area.get("components", [])
        eps = area.get("endpoints", [])
        if comps or eps:
            badges = (
                [f"`{c}`" for c in comps] + [f"`{e}`" for e in eps]
            )
            st.markdown(" · ".join(badges))

        cases = area.get("test_cases", [])
        for case in cases:
            ctype = (case.get("type") or "").lower()
            badge = "✓ POSITIVE" if ctype == "positive" else "✗ NEGATIVE"
            title = case.get("title", "")
            with st.expander(f"{badge} · {title}", expanded=False):
                st.write(case.get("description", ""))
                td = case.get("test_data", "")
                if td:
                    st.markdown(f"**Data:** {td}")

        if i < len(areas) - 1:
            st.markdown("---")


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

# Main: tabs
if graph is None:
    st.stop()

if "result" not in st.session_state:
    st.session_state["result"] = None
    st.session_state["scenario"] = ""

tab_scenario, tab_overview, tab_reverse = st.tabs(
    ["Scenario analysis", "System overview", "Reverse trace"]
)

# ── System overview tab ──────────────────────────────────────────────────────
with tab_overview:
    st.caption(
        "Auto-generated suggestion of feature areas and test cases for the whole "
        "system. Cached locally; regenerates only when the graph changes."
    )

    cache_exists = _OVERVIEW_CACHE.exists()
    cache_valid = False
    if cache_exists:
        try:
            cached = json.loads(_OVERVIEW_CACHE.read_text())
            cache_valid = cached.get("hash") == _graph_hash(graph)
        except (json.JSONDecodeError, KeyError):
            cache_valid = False

    col_a, col_b, _ = st.columns([2, 2, 6])
    with col_a:
        generate_clicked = st.button(
            "Generate" if not cache_valid else "Refresh",
            type="primary",
            use_container_width=True,
            help="Calls Claude to (re)build the system overview.",
        )
    with col_b:
        if cache_valid:
            st.caption("Cached overview matches current graph.")
        elif cache_exists:
            st.caption("Cache out of date (graph changed).")
        else:
            st.caption("No cache yet — click Generate.")

    overview = None
    if cache_valid and not generate_clicked:
        overview = cached["result"]
    elif generate_clicked:
        if not api_key:
            st.error("No Anthropic API key — paste one in the sidebar or set `ANTHROPIC_API_KEY`.")
        else:
            os.environ["ANTHROPIC_API_KEY"] = api_key
            with st.spinner("Generating system overview…"):
                try:
                    overview = load_system_overview(graph, force=True)
                except Exception as e:
                    st.error(f"Failed to generate overview: {e}")

    if overview:
        render_system_overview(overview)


# ── Scenario analysis tab ────────────────────────────────────────────────────
with tab_scenario:
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
            os.environ["ANTHROPIC_API_KEY"] = api_key
            with st.spinner("Calling Claude…"):
                try:
                    st.session_state["result"] = analyze_scenario(graph, scenario)
                    st.session_state["scenario"] = scenario
                except SystemExit:
                    st.error("Claude returned a response that couldn't be parsed as JSON. Try a more specific scenario.")
                    st.session_state["result"] = None
                except Exception as e:
                    st.error(f"Analysis failed: {e}")
                    st.session_state["result"] = None

    result = st.session_state["result"]
    if result is not None:
        render_full_result(graph, result)


# ── Reverse trace tab ────────────────────────────────────────────────────────
with tab_reverse:
    st.caption(
        "Pick any graph node — component, endpoint, or table. Claude finds "
        "distinct user flows that touch it, then drill into any one for the "
        "full analysis."
    )

    # Build the dropdown options (flat, prefixed by layer)
    options: list[tuple[str, str, str]] = []
    for c in graph["components"]:
        options.append(("component", c["id"], f"[Component] {c['id']}"))
    for e in graph["endpoints"]:
        options.append(("endpoint", e["id"], f"[Endpoint] {e['id']}"))
    for t in graph["tables"]:
        options.append(("table", t["id"], f"[Table] {t['id']}"))
    labels = [o[2] for o in options]

    selected_idx = st.selectbox(
        "Trace from",
        range(len(options)),
        format_func=lambda i: labels[i],
        key="reverse_target",
    )
    target_type, target_id, _ = options[selected_idx]

    col_t, _ = st.columns([1, 7])
    with col_t:
        trace_clicked = st.button("Trace", type="primary", use_container_width=True, key="reverse_trace_btn")

    if trace_clicked:
        if not api_key:
            st.error("No Anthropic API key — paste one in the sidebar or set `ANTHROPIC_API_KEY`.")
        else:
            os.environ["ANTHROPIC_API_KEY"] = api_key
            with st.spinner(f"Finding scenarios that touch {target_type} `{target_id}`…"):
                try:
                    st.session_state["reverse_result"] = find_scenarios_touching(
                        graph, target_type, target_id
                    )
                    st.session_state["reverse_drilldown"] = None
                except Exception as e:
                    st.error(f"Trace failed: {e}")
                    st.session_state["reverse_result"] = None

    rev = st.session_state.get("reverse_result")
    if rev:
        scenarios = rev.get("scenarios", [])
        tgt = rev.get("target", {})
        st.markdown(
            f"### {len(scenarios)} scenarios touching "
            f"`{tgt.get('id', target_id)}` ({tgt.get('type', target_type)})"
        )

        for i, sc in enumerate(scenarios):
            with st.container(border=True):
                st.markdown(f"**{sc.get('title', f'Scenario {i+1}')}**")
                st.write(sc.get("description", ""))
                badges = (
                    [f"`{c}`" for c in sc.get("components", [])]
                    + [f"`{e}`" for e in sc.get("endpoints", [])]
                    + [f"`{t}`" for t in sc.get("tables", [])]
                )
                if badges:
                    st.markdown(" · ".join(badges))
                if st.button("Drill into this scenario", key=f"drill_{i}"):
                    if not api_key:
                        st.error("No Anthropic API key.")
                    else:
                        os.environ["ANTHROPIC_API_KEY"] = api_key
                        scenario_text = f"{sc.get('title','')}: {sc.get('description','')}".strip(": ")
                        with st.spinner("Running full analysis…"):
                            try:
                                full = analyze_scenario(graph, scenario_text)
                                st.session_state["reverse_drilldown"] = {
                                    "index": i,
                                    "title": sc.get("title", ""),
                                    "result": full,
                                }
                            except SystemExit:
                                st.error("Claude returned a response that couldn't be parsed as JSON.")
                            except Exception as e:
                                st.error(f"Drill-down failed: {e}")

        drill = st.session_state.get("reverse_drilldown")
        if drill:
            st.markdown("---")
            st.markdown(f"### Drill-down: {drill.get('title', '')}")
            render_full_result(graph, drill["result"])
