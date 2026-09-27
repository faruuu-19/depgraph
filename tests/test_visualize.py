"""Unit tests for DependencyGraph.to_mermaid() and DependencyGraph.to_dot()."""

import re

import pytest
from dep_graph_guard.graph import DependencyGraph


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _simple_graph() -> DependencyGraph:
    """Two-node graph: main.py → utils.py (main imports utils)."""
    g = DependencyGraph()
    g.add_edge("main.py", "utils.py")
    return g


def _chain_graph() -> DependencyGraph:
    """Three-node chain: A → B → C."""
    g = DependencyGraph()
    g.add_edge("A", "B")
    g.add_edge("B", "C")
    return g


def _path_graph() -> DependencyGraph:
    """Graph whose node paths contain slashes and dots."""
    g = DependencyGraph()
    g.add_edge("services/booking.py", "models.py")
    g.add_edge("tests/test_booking.py", "services/booking.py")
    return g


def _empty_graph() -> DependencyGraph:
    return DependencyGraph()


# ===========================================================================
# to_mermaid
# ===========================================================================

class TestToMermaid:
    def test_starts_with_graph_td(self):
        """Output must start with the 'graph TD' directive."""
        result = _simple_graph().to_mermaid()
        assert result.startswith("graph TD")

    def test_contains_node_labels(self):
        """Every node path must appear as a quoted label."""
        result = _simple_graph().to_mermaid()
        assert '"main.py"' in result
        assert '"utils.py"' in result

    def test_edge_arrow_present(self):
        """Each import edge must produce a '-->' line."""
        result = _simple_graph().to_mermaid()
        assert "-->" in result

    def test_edge_direction(self):
        """The arrow must go from the importer to the importee."""
        result = _simple_graph().to_mermaid()
        lines = result.splitlines()
        # Find the edge line — must list the importer ID before the importee ID.
        arrow_lines = [l for l in lines if "-->" in l]
        assert len(arrow_lines) == 1
        lhs, rhs = arrow_lines[0].split("-->")
        # main_py node id appears on left, utils_py on right.
        assert "main_py" in lhs
        assert "utils_py" in rhs

    def test_slashes_and_dots_sanitised_in_ids(self):
        """Node IDs must not contain '/' or '.' — they must be replaced."""
        result = _path_graph().to_mermaid()
        # IDs appear before the '[' in declaration lines.
        id_pattern = re.compile(r'^\s+(\S+)\[', re.MULTILINE)
        ids = id_pattern.findall(result)
        for nid in ids:
            assert "/" not in nid, f"slash found in node ID: {nid!r}"
            assert "." not in nid, f"dot found in node ID: {nid!r}"

    def test_original_paths_used_as_labels(self):
        """Original paths (with slashes/dots) must be preserved as display labels."""
        result = _path_graph().to_mermaid()
        assert '"services/booking.py"' in result
        assert '"models.py"' in result
        assert '"tests/test_booking.py"' in result

    def test_chain_has_two_arrows(self):
        """A 3-node chain must produce exactly two edge lines."""
        result = _chain_graph().to_mermaid()
        arrow_lines = [l for l in result.splitlines() if "-->" in l]
        assert len(arrow_lines) == 2

    def test_empty_graph_is_valid(self):
        """An empty graph must still produce a valid 'graph TD' block."""
        result = _empty_graph().to_mermaid()
        assert result.strip() == "graph TD"

    def test_isolated_node_declared_without_edge(self):
        """A node with no edges must still appear in the declaration section."""
        g = DependencyGraph()
        g.add_node("orphan.py")
        result = g.to_mermaid()
        assert '"orphan.py"' in result
        assert "-->" not in result

    def test_output_is_deterministic(self):
        """Calling to_mermaid() twice must return the same string."""
        g = _path_graph()
        assert g.to_mermaid() == g.to_mermaid()


# ===========================================================================
# to_dot
# ===========================================================================

class TestToDot:
    def test_starts_with_digraph(self):
        """DOT output must open with a digraph block."""
        result = _simple_graph().to_dot()
        assert result.strip().startswith("digraph")

    def test_contains_arrow_operator(self):
        """Each import edge must use the '->' DOT operator."""
        result = _simple_graph().to_dot()
        assert "->" in result

    def test_node_paths_present(self):
        """Node paths must appear somewhere in the DOT output."""
        result = _simple_graph().to_dot()
        assert "main.py" in result
        assert "utils.py" in result

    def test_edge_direction(self):
        """The importer must appear on the left of '->' for each edge."""
        result = _simple_graph().to_dot()
        # Find lines containing '->'
        edge_lines = [l for l in result.splitlines() if "->" in l]
        assert len(edge_lines) >= 1
        for line in edge_lines:
            lhs, rhs = line.split("->")
            assert "main.py" in lhs
            assert "utils.py" in rhs

    def test_empty_graph_is_valid(self):
        """An empty graph must still produce a syntactically valid DOT block."""
        result = _empty_graph().to_dot()
        assert "digraph" in result
        assert result.strip().endswith("}")

    def test_paths_with_slashes_are_quoted(self):
        """Paths containing '/' must be wrapped in double-quotes in the DOT output."""
        result = _path_graph().to_dot()
        assert '"services/booking.py"' in result
        assert '"models.py"' in result

    def test_output_is_deterministic(self):
        """Calling to_dot() twice must return the same string."""
        g = _path_graph()
        assert g.to_dot() == g.to_dot()


# ===========================================================================
# visualize_dependency_graph (server-level)
# ===========================================================================

class TestVisualizeDependencyGraph:
    """Light smoke-tests for the MCP tool wrapper in server.py."""

    def test_mermaid_format(self, tmp_path):
        """visualize_dependency_graph with format='mermaid' must return a mermaid string."""
        from dep_graph_guard.server import visualize_dependency_graph

        # Build a minimal repo with one Python file that imports another.
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "a.py").write_text("from pkg import b\n")
        (pkg / "b.py").write_text("x = 1\n")
        (tmp_path / "__init__.py").write_text("")

        result = visualize_dependency_graph(str(tmp_path), "mermaid")
        assert result.startswith("graph TD")

    def test_dot_format(self, tmp_path):
        """visualize_dependency_graph with format='dot' must return a DOT string."""
        from dep_graph_guard.server import visualize_dependency_graph

        (tmp_path / "a.py").write_text("import b\n")
        (tmp_path / "b.py").write_text("x = 1\n")

        result = visualize_dependency_graph(str(tmp_path), "dot")
        assert "digraph" in result

    def test_invalid_format_raises(self, tmp_path):
        """An unknown output_format must raise ValueError."""
        from dep_graph_guard.server import visualize_dependency_graph

        (tmp_path / "a.py").write_text("")
        with pytest.raises(ValueError, match="Unsupported output_format"):
            visualize_dependency_graph(str(tmp_path), "xml")
