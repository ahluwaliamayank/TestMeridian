"""
diff_impact.py
--------------
Pure-logic helpers for the "Diff impact" feature:

  - Find the git repo root from the analyzer's CWD.
  - Run `git diff --name-only <ref>` and parse the file list.
  - Map changed files to graph nodes (components, endpoints, schema files).
  - Compute the blast-radius subgraph (forward + backward propagation).

No LLM calls happen here; everything is deterministic.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


# Files that, when changed, imply schema/model-level changes - all tables get
# flagged as potentially affected. Conservative on purpose.
_SCHEMA_FILENAME_HINTS = ("models.py", "schema.sql")


# ── Repo discovery ──────────────────────────────────────────────────────────

def find_repo_root(start: Path | str = ".") -> Path | None:
    """
    Locate the git repo root.

    Order of precedence:
      1. `IMPACTMAP_REPO_ROOT` env var, if set and the path contains `.git`.
         This is the escape hatch for Docker setups where CWD is not inside
         the repo tree but `.git` is bind-mounted elsewhere.
      2. Walk upward from `start` looking for a `.git` directory.
    """
    override = os.environ.get("IMPACTMAP_REPO_ROOT")
    if override:
        op = Path(override)
        if (op / ".git").exists():
            return op

    p = Path(start).resolve()
    for ancestor in (p, *p.parents):
        if (ancestor / ".git").exists():
            return ancestor
    return None


# ── Diff parsing ────────────────────────────────────────────────────────────

def get_changed_files(repo_dir: Path, ref: str) -> list[str]:
    """
    Run `git diff --name-only <ref>` inside `repo_dir`.

    `ref` can be:
      - 'main...HEAD'   - branch vs main (PR scenario)
      - 'HEAD'          - uncommitted changes (working tree vs HEAD)
      - '--cached'      - staged changes
      - 'HEAD~1..HEAD'  - last commit only
    """
    cmd = ["git", "diff", "--name-only", *ref.split()]
    result = subprocess.run(
        cmd, cwd=repo_dir, capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git diff failed (exit {result.returncode}): {result.stderr.strip()}"
        )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


# ── File → graph-node mapping ────────────────────────────────────────────────

def _file_matches(node_file: str, changed_file: str) -> bool:
    """
    A node matches a changed file when one path is a suffix of the other.
    Handles the fact that node files are stored relative to the UI/API roots,
    while `git diff` returns paths relative to the repo root.
    """
    return node_file.endswith(changed_file) or changed_file.endswith(node_file)


def categorize_changed_files(graph: dict, changed_files: list[str]) -> dict:
    """
    Given the changed-file list, identify which graph nodes are directly affected.

    Returns:
      {
        "changed_components": [component dicts],
        "changed_endpoints":  [endpoint dicts],
        "schema_files":       [file paths matching schema patterns],
        "unmapped_files":     [paths we couldn't attribute to any node],
      }
    """
    changed_components: list[dict] = []
    changed_endpoints: list[dict] = []
    schema_files: list[str] = []
    mapped: set[str] = set()

    for f in changed_files:
        basename = os.path.basename(f)

        for c in graph["components"]:
            if _file_matches(c["file"], f):
                if c not in changed_components:
                    changed_components.append(c)
                mapped.add(f)

        for e in graph["endpoints"]:
            if _file_matches(e["file"], f):
                if e not in changed_endpoints:
                    changed_endpoints.append(e)
                mapped.add(f)

        if any(hint in basename for hint in _SCHEMA_FILENAME_HINTS) or f.endswith(".sql"):
            schema_files.append(f)
            mapped.add(f)

    return {
        "changed_components": changed_components,
        "changed_endpoints":  changed_endpoints,
        "schema_files":       schema_files,
        "unmapped_files":     [f for f in changed_files if f not in mapped],
    }


# ── Blast-radius traversal ───────────────────────────────────────────────────

def compute_blast_radius(graph: dict,
                          changed_component_ids: set[str],
                          changed_endpoint_ids: set[str],
                          changed_table_ids: set[str]) -> tuple[set[str], set[str], set[str]]:
    """
    Walk both directions through the dependency graph from the changed nodes.

    Forward propagation:
      component → endpoints it calls → tables those endpoints touch
    Backward propagation:
      table → endpoints that touch it → components that call those endpoints

    Returns (reachable_components, reachable_endpoints, reachable_tables) -
    each set includes the originally-changed ids plus everything reachable.
    """
    comps = set(changed_component_ids)
    eps = set(changed_endpoint_ids)
    tables = set(changed_table_ids)

    c2e = graph["edges"]["component_to_endpoint"]
    e2t = graph["edges"]["endpoint_to_table"]

    # Forward: components → endpoints
    for edge in c2e:
        if edge["from"] in comps:
            eps.add(edge["to"])
    # Forward: endpoints → tables
    for edge in e2t:
        if edge["from"] in eps:
            tables.add(edge["to"])
    # Backward: tables → endpoints
    for edge in e2t:
        if edge["to"] in tables:
            eps.add(edge["from"])
    # Backward: endpoints → components
    for edge in c2e:
        if edge["to"] in eps:
            comps.add(edge["from"])

    return comps, eps, tables
