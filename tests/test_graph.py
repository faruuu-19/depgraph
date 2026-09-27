"""Unit tests for dep_graph_guard.graph.DependencyGraph."""

import pytest
from dep_graph_guard.graph import DependencyGraph


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _chain_graph() -> DependencyGraph:
    """Return a graph with the 3-node chain A → B → C.

    Edge direction: A imports B, B imports C.
    So: downstream(C) = {A, B}, upstream(A) = {B, C}.
    """
    g = DependencyGraph()
    g.add_edge("A", "B")
    g.add_edge("B", "C")
    return g


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

class TestAddNode:
    def test_add_node_idempotent(self):
        """Calling add_node twice for the same path must not duplicate the node."""
        g = DependencyGraph()
        g.add_node("a.py")
        g.add_node("a.py")
        assert len(g) == 1

    def test_add_node_stores_attrs(self):
        """Extra keyword attributes are stored on the node."""
        g = DependencyGraph()
        g.add_node("a.py", node_kind="module", owner="team-a")
        data = g.to_dict()
        node = next(n for n in data["nodes"] if n["path"] == "a.py")
        assert node["node_kind"] == "module"
        assert node["owner"] == "team-a"


class TestAddEdge:
    def test_add_edge_auto_creates_nodes(self):
        """add_edge must auto-create both endpoint nodes when they don't exist."""
        g = DependencyGraph()
        g.add_edge("main.py", "utils.py")
        assert len(g) == 2

    def test_add_edge_idempotent(self):
        """Calling add_edge twice for the same endpoints keeps only one edge."""
        g = DependencyGraph()
        g.add_edge("a.py", "b.py")
        g.add_edge("a.py", "b.py")
        data = g.to_dict()
        edges = [e for e in data["edges"] if e["from"] == "a.py" and e["to"] == "b.py"]
        assert len(edges) == 1


class TestDownstream:
    def test_downstream_chain(self):
        """downstream(C) on chain A→B→C must return {A, B}."""
        g = _chain_graph()
        assert g.downstream("C") == {"A", "B"}

    def test_downstream_no_dependents(self):
        """downstream on a leaf node (nothing imports it) must return empty set."""
        g = _chain_graph()
        # A is the root importer — nothing imports A.
        assert g.downstream("A") == set()


class TestUpstream:
    def test_upstream_chain(self):
        """upstream(A) on chain A→B→C must return {B, C}."""
        g = _chain_graph()
        assert g.upstream("A") == {"B", "C"}


class TestToDict:
    def test_to_dict_structure(self):
        """to_dict must contain 'nodes' and 'edges' with correct counts."""
        g = _chain_graph()
        d = g.to_dict()
        assert set(d.keys()) == {"nodes", "edges"}
        assert len(d["nodes"]) == 3   # A, B, C
        assert len(d["edges"]) == 2   # A→B, B→C

    def test_to_dict_edge_keys(self):
        """Each edge dict must have 'from', 'to', and 'dep_kind' keys."""
        g = DependencyGraph()
        g.add_edge("x.py", "y.py", dep_kind="import")
        edge = g.to_dict()["edges"][0]
        assert edge["from"] == "x.py"
        assert edge["to"] == "y.py"
        assert edge["dep_kind"] == "import"


class TestLen:
    def test_len_counts_nodes(self):
        """__len__ must return the number of nodes."""
        g = DependencyGraph()
        assert len(g) == 0
        g.add_node("a.py")
        g.add_node("b.py")
        assert len(g) == 2
