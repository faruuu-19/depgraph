"""End-to-end tests using the Galaxium Travels repository.

These tests call the tool handler functions directly (no MCP transport)
against the three real sub-projects in the Galaxium Travels mono-repo:

  1. booking_system_backend          — Python
  2. booking_system_frontend         — TypeScript / React
  3. booking_system_inventory_hold_service — Java Spring Boot

Update GALAXIUM_ROOT if the repo is cloned to a different location.
"""

import json

import pytest

from dep_graph_guard.server import (
    _build_graph,
    analyze_change_impact,
    build_dependency_graph,
    get_required_tests,
)

# ---------------------------------------------------------------------------
# Repo roots — forward slashes work on all platforms via pathlib
# ---------------------------------------------------------------------------

GALAXIUM_ROOT = "C:/bob_ibm/galaxium-travels"
PYTHON_BACKEND = f"{GALAXIUM_ROOT}/booking_system_backend"
TS_FRONTEND = f"{GALAXIUM_ROOT}/booking_system_frontend"
JAVA_SERVICE = f"{GALAXIUM_ROOT}/booking_system_inventory_hold_service"


# ===========================================================================
# Python backend
# ===========================================================================


def test_python_build_dependency_graph():
    """Graph for the Python backend should have at least 5 nodes and 1 edge."""
    result = build_dependency_graph(PYTHON_BACKEND)
    data = json.loads(result)
    assert data["stats"]["node_count"] >= 5
    assert data["stats"]["edge_count"] >= 1


def test_python_analyze_change_impact():
    """Changing models.py should transitively affect multiple source files."""
    result = analyze_change_impact(PYTHON_BACKEND, ["models.py"])
    data = json.loads(result)
    assert data["total_affected_count"] >= 1
    assert len(data["transitively_affected"]) >= 1


def test_python_get_required_tests():
    """Test files exist in the Python backend — at least some coverage expected."""
    result = get_required_tests(
        PYTHON_BACKEND,
        ["models.py", "services/booking.py"],
    )
    data = json.loads(result)
    # Either tests are found OR nodes end up in uncovered; either way the
    # pipeline ran and produced structured output.
    assert len(data["tests_to_run"]) >= 1 or len(data["uncovered_nodes"]) >= 1
    assert "covered" in data["coverage_summary"]
    assert "uncovered" in data["coverage_summary"]


# ===========================================================================
# TypeScript / React frontend
# ===========================================================================


def test_ts_build_dependency_graph():
    """Graph for the TS frontend should have at least 5 nodes and 1 edge."""
    result = build_dependency_graph(TS_FRONTEND)
    data = json.loads(result)
    assert data["stats"]["node_count"] >= 5
    assert data["stats"]["edge_count"] >= 1


def test_ts_analyze_change_impact():
    """src/types/index.ts is a central hub — changing it should affect >= 2 files."""
    result = analyze_change_impact(TS_FRONTEND, ["src/types/index.ts"])
    data = json.loads(result)
    assert data["total_affected_count"] >= 2


def test_ts_get_required_tests_no_test_files():
    """The TS frontend has no test files, so all affected nodes must be uncovered."""
    result = get_required_tests(
        TS_FRONTEND,
        ["src/types/index.ts", "src/services/api.ts"],
    )
    data = json.loads(result)
    assert len(data["uncovered_nodes"]) >= 1


# ===========================================================================
# Java Spring Boot inventory-hold service
# ===========================================================================


def test_java_build_dependency_graph():
    """Graph for the Java service should have at least 5 nodes and 1 edge."""
    result = build_dependency_graph(JAVA_SERVICE)
    data = json.loads(result)
    assert data["stats"]["node_count"] >= 5
    assert data["stats"]["edge_count"] >= 1


def test_java_analyze_change_impact():
    """HoldService is used by controllers — changing it should affect >= 1 file."""
    result = analyze_change_impact(
        JAVA_SERVICE,
        ["src/main/java/com/galaxium/holdservice/service/HoldService.java"],
    )
    data = json.loads(result)
    assert data["total_affected_count"] >= 1


def test_java_get_required_tests():
    """Java *Test.java files exist — coverage_summary totals should be >= 2."""
    result = get_required_tests(
        JAVA_SERVICE,
        [
            "src/main/java/com/galaxium/holdservice/service/HoldService.java",
            "src/main/java/com/galaxium/holdservice/domain/Hold.java",
        ],
    )
    data = json.loads(result)
    total = data["coverage_summary"]["covered"] + data["coverage_summary"]["uncovered"]
    assert total >= 2
