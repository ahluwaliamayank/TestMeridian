"""
dashboard.py
------------
Streamlit dashboard for TestMeridian.

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

from analyze import (
    analyze_scenario,
    analyze_system,
    find_scenarios_touching,
    analyze_diff_impact,
)
from diff_impact import (
    find_repo_root,
    get_changed_files,
    categorize_changed_files,
    compute_blast_radius,
)


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
CHANGED_BORDER   = "#dc2626"   # red border for nodes that were directly changed


# ── DOT graph builder ────────────────────────────────────────────────────────

def _q(s: str) -> str:
    """Quote an identifier for DOT, escaping internal quotes."""
    return '"' + s.replace('"', '\\"') + '"'


def build_dot(graph: dict,
              components_touched: set[str],
              endpoints_touched: set[str],
              tables_touched: set[str],
              components_changed: set[str] | None = None,
              endpoints_changed: set[str] | None = None,
              tables_changed: set[str] | None = None) -> str:
    """
    Render the dependency graph as DOT.

    `components_touched` etc. are the highlight set (active color).
    `*_changed` (optional) are nodes that were *directly* changed - they get
    a red border on top of the active color, to distinguish them from
    reachable-but-unchanged nodes in the diff-impact view.
    """
    components_changed = components_changed or set()
    endpoints_changed  = endpoints_changed or set()
    tables_changed     = tables_changed or set()

    def _attrs(active: bool, changed: bool, active_fill: str, dim_fill: str) -> str:
        fill = active_fill if active else dim_fill
        fontcolor = "white" if active else "#666"
        attrs = f'fillcolor="{fill}", fontcolor="{fontcolor}"'
        if changed:
            attrs += f', color="{CHANGED_BORDER}", penwidth=3'
        return attrs

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
        attrs = _attrs(
            c["id"] in components_touched,
            c["id"] in components_changed,
            COMPONENT_ACTIVE, COMPONENT_DIM,
        )
        lines.append(f'    {_q(c["id"])} [{attrs}];')
    lines.append('  }')

    # ── API cluster ──────────────────────────────────────────────────────────
    lines.append('  subgraph cluster_api {')
    lines.append('    label="API"; style="rounded"; color="#bbbbbb"; fontname="Helvetica";')
    for ep in graph["endpoints"]:
        attrs = _attrs(
            ep["id"] in endpoints_touched,
            ep["id"] in endpoints_changed,
            ENDPOINT_ACTIVE, ENDPOINT_DIM,
        )
        lines.append(f'    {_q(ep["id"])} [{attrs}];')
    lines.append('  }')

    # ── DB cluster ───────────────────────────────────────────────────────────
    lines.append('  subgraph cluster_db {')
    lines.append('    label="DB"; style="rounded"; color="#bbbbbb"; fontname="Helvetica";')
    for t in graph["tables"]:
        attrs = _attrs(
            t["id"] in tables_touched,
            t["id"] in tables_changed,
            TABLE_ACTIVE, TABLE_DIM,
        )
        lines.append(f'    {_q(t["id"])} [shape=cylinder, {attrs}];')
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
                f"**{step.get('step', '?')}.** `{step.get('component', '')}` - "
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
                f"**`{t.get('table', '')}`** - {ops}  \n"
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
    page_title="TestMeridian",
    page_icon=None,
    layout="wide",
)

st.title("TestMeridian")
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

tab_scenario, tab_overview, tab_reverse, tab_diff = st.tabs(
    ["Scenario analysis", "System overview", "Reverse trace", "Diff impact"]
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
            help="Generates a fresh system overview.",
        )
    with col_b:
        if cache_valid:
            st.caption("Cached overview matches current graph.")
        elif cache_exists:
            st.caption("Cache out of date (graph changed).")
        else:
            st.caption("No cache yet - click Generate.")

    overview = None
    if cache_valid and not generate_clicked:
        overview = cached["result"]
    elif generate_clicked:
        if not api_key:
            st.error("No Anthropic API key - paste one in the sidebar or set `ANTHROPIC_API_KEY`.")
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
            st.error("No Anthropic API key - paste one in the sidebar or set `ANTHROPIC_API_KEY` in your shell.")
        else:
            os.environ["ANTHROPIC_API_KEY"] = api_key
            with st.spinner("Analyzing…"):
                try:
                    st.session_state["result"] = analyze_scenario(graph, scenario)
                    st.session_state["scenario"] = scenario
                except SystemExit:
                    st.error("The response could not be parsed as JSON. Try a more specific scenario.")
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
        "Pick any graph node - component, endpoint, or table. The analyzer finds "
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
            st.error("No Anthropic API key - paste one in the sidebar or set `ANTHROPIC_API_KEY`.")
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
                                st.error("The response could not be parsed as JSON.")
                            except Exception as e:
                                st.error(f"Drill-down failed: {e}")

        drill = st.session_state.get("reverse_drilldown")
        if drill:
            st.markdown("---")
            st.markdown(f"### Drill-down: {drill.get('title', '')}")
            render_full_result(graph, drill["result"])


# ── Diff impact tab ──────────────────────────────────────────────────────────
with tab_diff:
    st.caption(
        "Point at a git ref. The analyzer maps changed files to graph nodes, computes "
        "the blast radius, and ranks the test scenarios you should run - by risk."
    )

    repo_root = find_repo_root(Path.cwd())
    if repo_root is None:
        st.error("Not inside a git repository - diff impact requires one. "
                 "Run the dashboard from a working tree with a `.git` directory.")
    else:
        st.caption(f"Repo: `{repo_root}`")

        col_ref, col_btn, _ = st.columns([3, 1, 4])
        with col_ref:
            ref = st.text_input(
                "Diff ref",
                value="main...HEAD",
                help=(
                    "Examples:\n"
                    "  • `main...HEAD` - current branch vs main (PR scenario)\n"
                    "  • `HEAD` - uncommitted working-tree changes\n"
                    "  • `--cached` - staged changes\n"
                    "  • `HEAD~1..HEAD` - last commit only"
                ),
                key="diff_ref",
            )
        with col_btn:
            diff_clicked = st.button(
                "Analyze diff", type="primary", use_container_width=True, key="diff_analyze_btn",
            )

        if diff_clicked:
            try:
                changed_files = get_changed_files(repo_root, ref)
            except RuntimeError as e:
                st.error(str(e))
                changed_files = None

            if changed_files is not None:
                if not changed_files:
                    st.info("No files changed for that ref - nothing to analyze.")
                    st.session_state["diff_result"] = None
                else:
                    categorized = categorize_changed_files(graph, changed_files)

                    # Schema-file changes flag all tables as directly changed.
                    if categorized["schema_files"]:
                        changed_table_ids = {t["id"] for t in graph["tables"]}
                    else:
                        changed_table_ids = set()

                    changed_comp_ids = {c["id"] for c in categorized["changed_components"]}
                    changed_ep_ids   = {e["id"] for e in categorized["changed_endpoints"]}

                    blast_c, blast_e, blast_t = compute_blast_radius(
                        graph, changed_comp_ids, changed_ep_ids, changed_table_ids,
                    )

                    diff_summary = {
                        "changed_files":      changed_files,
                        "changed_components": categorized["changed_components"],
                        "changed_endpoints":  categorized["changed_endpoints"],
                        "schema_files":       categorized["schema_files"],
                        "unmapped_files":     categorized["unmapped_files"],
                        "changed_component_ids": changed_comp_ids,
                        "changed_endpoint_ids":  changed_ep_ids,
                        "changed_table_ids":     changed_table_ids,
                        "blast_components":   blast_c,
                        "blast_endpoints":    blast_e,
                        "blast_tables":       blast_t,
                    }

                    if not api_key:
                        st.error("No Anthropic API key - paste one in the sidebar.")
                        st.session_state["diff_summary"] = diff_summary
                        st.session_state["diff_result"] = None
                    else:
                        os.environ["ANTHROPIC_API_KEY"] = api_key
                        with st.spinner("Ranking impacted scenarios…"):
                            try:
                                st.session_state["diff_summary"] = diff_summary
                                st.session_state["diff_result"]  = analyze_diff_impact(graph, diff_summary)
                                st.session_state["diff_drilldown"] = None
                            except Exception as e:
                                st.error(f"Diff analysis failed: {e}")
                                st.session_state["diff_result"] = None

        # Render summary + radius + scenarios from session state
        diff_summary = st.session_state.get("diff_summary")
        diff_result  = st.session_state.get("diff_result")

        if diff_summary:
            st.markdown("### Diff summary")
            with st.container(border=True):
                st.markdown(f"**{len(diff_summary['changed_files'])} files changed**")
                for f in diff_summary["changed_files"]:
                    st.markdown(f"- `{f}`")

                mapping_lines = []
                if diff_summary["changed_components"]:
                    mapping_lines.append(
                        f"**Components:** "
                        + ", ".join(f"`{c['id']}`" for c in diff_summary["changed_components"])
                    )
                if diff_summary["changed_endpoints"]:
                    mapping_lines.append(
                        f"**Endpoints:** "
                        + ", ".join(f"`{e['id']}`" for e in diff_summary["changed_endpoints"])
                    )
                if diff_summary["schema_files"]:
                    mapping_lines.append(
                        f"**Schema files:** "
                        + ", ".join(f"`{f}`" for f in diff_summary["schema_files"])
                        + " - all tables flagged as potentially changed"
                    )
                if diff_summary["unmapped_files"]:
                    mapping_lines.append(
                        f"_Unmapped (not in graph):_ "
                        + ", ".join(f"`{f}`" for f in diff_summary["unmapped_files"])
                    )
                if mapping_lines:
                    st.markdown("---")
                    for ln in mapping_lines:
                        st.markdown(ln)

            st.markdown("### Blast radius")
            dot = build_dot(
                graph,
                components_touched=diff_summary["blast_components"],
                endpoints_touched=diff_summary["blast_endpoints"],
                tables_touched=diff_summary["blast_tables"],
                components_changed=diff_summary["changed_component_ids"],
                endpoints_changed=diff_summary["changed_endpoint_ids"],
                tables_changed=diff_summary["changed_table_ids"],
            )
            st.graphviz_chart(dot, use_container_width=True)
            st.caption("Red border = directly changed · solid color = in blast radius · dimmed = untouched")

        if diff_result:
            st.markdown("### Suggested tests (ranked by risk)")
            summary_text = diff_result.get("summary", "")
            if summary_text:
                st.info(summary_text)

            scenarios = diff_result.get("scenarios", [])
            risk_order = {"high": 0, "medium": 1, "low": 2}
            scenarios = sorted(scenarios, key=lambda s: risk_order.get((s.get("risk") or "").lower(), 99))

            for i, sc in enumerate(scenarios):
                risk = (sc.get("risk") or "").lower()
                ctype = (sc.get("type") or "").lower()
                risk_label = {"high": "[HIGH]", "medium": "[MED]", "low": "[LOW]"}.get(risk, "[-]")
                type_label = "✓ POS" if ctype == "positive" else "✗ NEG" if ctype == "negative" else "·"
                with st.container(border=True):
                    st.markdown(f"**{risk_label}**  {type_label}  **{sc.get('title','')}**")
                    st.write(sc.get("description", ""))
                    cc = sc.get("covers_changes", [])
                    if cc:
                        st.markdown("_Covers changes:_ " + ", ".join(f"`{c}`" for c in cc))
                    td = sc.get("test_data", "")
                    if td:
                        st.markdown(f"**Data:** {td}")
                    if st.button("Drill into this scenario", key=f"diff_drill_{i}"):
                        if not api_key:
                            st.error("No Anthropic API key.")
                        else:
                            os.environ["ANTHROPIC_API_KEY"] = api_key
                            scenario_text = f"{sc.get('title','')}: {sc.get('description','')}".strip(": ")
                            with st.spinner("Running full analysis…"):
                                try:
                                    full = analyze_scenario(graph, scenario_text)
                                    st.session_state["diff_drilldown"] = {
                                        "index": i,
                                        "title": sc.get("title", ""),
                                        "result": full,
                                    }
                                except SystemExit:
                                    st.error("The response could not be parsed as JSON.")
                                except Exception as e:
                                    st.error(f"Drill-down failed: {e}")

            drill = st.session_state.get("diff_drilldown")
            if drill:
                st.markdown("---")
                st.markdown(f"### Drill-down: {drill.get('title', '')}")
                render_full_result(graph, drill["result"])
