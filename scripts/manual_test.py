"""Manual test script for dep-graph-guard tool handlers.

Run from the dep-graph-guard directory with the package installed:

    python scripts/manual_test.py

Or, without installing, with the package source on the path:

    cd dep-graph-guard
    python scripts/manual_test.py

Steps
-----
1. build_dependency_graph  — scan the Python backend and print graph stats.
2. analyze_change_impact   — find everything affected by models.py changing.
3. get_required_tests      — map the affected nodes from step 2 to test files.

Note: the tool functions accept a *repo_path* root and file paths that are
relative to that root.  We use the booking_system_backend sub-project as the
root so that nodes are stored as plain names like "models.py", matching the
pattern used by the parsers.  The e2e tests in tests/e2e/test_galaxium.py use
the same convention.
"""

import json
import sys
from pathlib import Path

# Allow running without installing the package by adding src/ to sys.path.
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dep_graph_guard.server import (
    analyze_change_impact,
    build_dependency_graph,
    get_required_tests,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

GALAXIUM_ROOT = "C:/bob_ibm/galaxium-travels"
# Use the backend sub-project as the repo root so relative paths resolve
# correctly inside the graph (e.g. "models.py", not "booking_system_backend/models.py").
REPO_PATH = f"{GALAXIUM_ROOT}/booking_system_backend"
CHANGED_FILES = ["models.py"]


def _pretty(data: dict) -> str:
    return json.dumps(data, indent=2)


def _header(title: str) -> None:
    bar = "=" * 60
    print(f"\n{bar}")
    print(f"  {title}")
    print(f"{bar}")


# ---------------------------------------------------------------------------
# Step 1 — build_dependency_graph
# ---------------------------------------------------------------------------

_header("STEP 1: build_dependency_graph")
print(f"repo_path = {REPO_PATH!r}\n")

graph_json = build_dependency_graph(REPO_PATH)
graph_data = json.loads(graph_json)

print(f"Nodes : {graph_data['stats']['node_count']}")
print(f"Edges : {graph_data['stats']['edge_count']}")
print("\nFull result:")
print(_pretty(graph_data))

# ---------------------------------------------------------------------------
# Step 2 — analyze_change_impact
# ---------------------------------------------------------------------------

_header("STEP 2: analyze_change_impact")
print(f"repo_path     = {REPO_PATH!r}")
print(f"changed_files = {CHANGED_FILES!r}\n")

impact_json = analyze_change_impact(REPO_PATH, CHANGED_FILES)
impact_data = json.loads(impact_json)

print(f"Directly affected    : {len(impact_data['directly_affected'])} file(s)")
for f in impact_data["directly_affected"]:
    print(f"  {f}")

print(f"\nTransitively affected: {impact_data['total_affected_count']} file(s)")
for f in impact_data["transitively_affected"]:
    print(f"  {f}")

print("\nFull result:")
print(_pretty(impact_data))

affected_nodes: list[str] = impact_data["transitively_affected"]

# ---------------------------------------------------------------------------
# Step 3 — get_required_tests
# ---------------------------------------------------------------------------

_header("STEP 3: get_required_tests")
print(f"repo_path      = {REPO_PATH!r}")
print(f"affected_nodes = {affected_nodes!r}\n")

tests_json = get_required_tests(REPO_PATH, affected_nodes)
tests_data = json.loads(tests_json)

print(f"Tests to run : {len(tests_data['tests_to_run'])} file(s)")
for t in tests_data["tests_to_run"]:
    print(f"  {t}")

print(f"\nUncovered    : {len(tests_data['uncovered_nodes'])} node(s)")
for n in tests_data["uncovered_nodes"]:
    print(f"  {n}")

print(f"\nCoverage summary: {tests_data['coverage_summary']}")
print("\nFull result:")
print(_pretty(tests_data))

_header("DONE")
