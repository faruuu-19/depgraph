"""tests/test_test_mapper.py — unit tests for TestMapper (Sub-Task 6).

Test cases
----------
1. Python convention  : test_foo.py identified as test node; covers src/foo.py by name.
2. JS/TS convention   : utils.test.ts identified as test node; covers src/utils.ts by name.
3. Java convention    : HelperTest.java identified as test node; covers src/Helper.java by name.
4. Config override    : dep-graph-guard.json with {"test_patterns": ["*_spec.rb"]}
                        causes foo_spec.rb to be detected as a test node.
5. Uncovered node     : a node with no matching test appears in uncovered_nodes.
6. Graph-edge coverage: a test file that imports a source file covers it via edge,
                        even without a name match.
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from dep_graph_guard.graph import DependencyGraph
from dep_graph_guard.test_mapper import TestMapper


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_graph(*node_paths: str, edges: list[tuple[str, str]] | None = None) -> DependencyGraph:
    """Create a DependencyGraph with the given nodes and optional edges."""
    g = DependencyGraph()
    for path in node_paths:
        g.add_node(path)
    for from_path, to_path in (edges or []):
        g.add_edge(from_path, to_path)
    return g


def _mapper(tmp_path, config: dict | None = None) -> TestMapper:
    """Return a TestMapper rooted at *tmp_path*, optionally writing a config."""
    if config is not None:
        config_file = os.path.join(str(tmp_path), "dep-graph-guard.json")
        with open(config_file, "w", encoding="utf-8") as fh:
            json.dump(config, fh)
    return TestMapper(str(tmp_path))


# ---------------------------------------------------------------------------
# Test 1: Python convention
# ---------------------------------------------------------------------------

def test_python_convention_find_and_map(tmp_path):
    """test_foo.py is detected as a test node and covers src/foo.py by name."""
    graph = _make_graph("src/foo.py", "tests/test_foo.py")
    mapper = _mapper(tmp_path)

    test_nodes = mapper.find_test_nodes(graph)
    assert "tests/test_foo.py" in test_nodes
    assert "src/foo.py" not in test_nodes

    result = mapper.map_to_tests(["src/foo.py"], graph)
    assert "tests/test_foo.py" in result["tests_to_run"]
    assert result["uncovered_nodes"] == []
    assert result["coverage_summary"]["covered"] == 1
    assert result["coverage_summary"]["uncovered"] == 0


# ---------------------------------------------------------------------------
# Test 2: JS/TS convention
# ---------------------------------------------------------------------------

def test_js_ts_convention(tmp_path):
    """utils.test.ts is detected as a test node and covers src/utils.ts by name."""
    graph = _make_graph("src/utils.ts", "src/utils.test.ts")
    mapper = _mapper(tmp_path)

    test_nodes = mapper.find_test_nodes(graph)
    assert "src/utils.test.ts" in test_nodes
    assert "src/utils.ts" not in test_nodes

    result = mapper.map_to_tests(["src/utils.ts"], graph)
    assert "src/utils.test.ts" in result["tests_to_run"]
    assert result["uncovered_nodes"] == []


# ---------------------------------------------------------------------------
# Test 3: Java convention
# ---------------------------------------------------------------------------

def test_java_convention(tmp_path):
    """HelperTest.java is detected as a test node and covers src/Helper.java by name."""
    graph = _make_graph("src/Helper.java", "src/HelperTest.java")
    mapper = _mapper(tmp_path)

    test_nodes = mapper.find_test_nodes(graph)
    assert "src/HelperTest.java" in test_nodes
    assert "src/Helper.java" not in test_nodes

    result = mapper.map_to_tests(["src/Helper.java"], graph)
    assert "src/HelperTest.java" in result["tests_to_run"]
    assert result["uncovered_nodes"] == []


# ---------------------------------------------------------------------------
# Test 4: Config override — Ruby spec pattern
# ---------------------------------------------------------------------------

def test_config_override_ruby_spec(tmp_path):
    """dep-graph-guard.json {"test_patterns": ["*_spec.rb"]} detects foo_spec.rb."""
    graph = _make_graph("lib/foo.rb", "spec/foo_spec.rb")
    mapper = _mapper(tmp_path, config={"test_patterns": ["*_spec.rb"]})

    test_nodes = mapper.find_test_nodes(graph)
    assert "spec/foo_spec.rb" in test_nodes
    assert "lib/foo.rb" not in test_nodes


# ---------------------------------------------------------------------------
# Test 5: Uncovered node
# ---------------------------------------------------------------------------

def test_uncovered_node(tmp_path):
    """A source node with no matching test file appears in uncovered_nodes."""
    graph = _make_graph("src/orphan.py", "tests/test_something_else.py")
    mapper = _mapper(tmp_path)

    result = mapper.map_to_tests(["src/orphan.py"], graph)
    assert "src/orphan.py" in result["uncovered_nodes"]
    assert result["tests_to_run"] == []
    assert result["coverage_summary"]["uncovered"] == 1
    assert result["coverage_summary"]["covered"] == 0


# ---------------------------------------------------------------------------
# Test 6: Graph-edge coverage
# ---------------------------------------------------------------------------

def test_graph_edge_coverage(tmp_path):
    """A test file that imports a source file covers it via graph edge,
    even when the file names do not follow any naming convention."""
    # "tests/integration_suite.py" doesn't match test_{stem}.py for "src/engine.py"
    # but it has an edge: integration_suite.py → engine.py  (imports engine)
    graph = _make_graph(
        "src/engine.py",
        "tests/integration_suite.py",
        edges=[("tests/integration_suite.py", "src/engine.py")],
    )
    # Mark integration_suite.py as a test node by placing it in tests/ dir.
    mapper = _mapper(tmp_path)

    test_nodes = mapper.find_test_nodes(graph)
    assert "tests/integration_suite.py" in test_nodes, (
        "File inside 'tests/' directory should be identified as a test node"
    )

    result = mapper.map_to_tests(["src/engine.py"], graph)
    assert "tests/integration_suite.py" in result["tests_to_run"], (
        "Graph-edge importer should count as covering the source node"
    )
    assert result["uncovered_nodes"] == []
