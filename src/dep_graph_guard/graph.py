"""graph.py — in-memory dependency graph built on networkx.DiGraph.

Edge direction convention:
    A → B  means "A depends on / imports B".

Consequently:
    downstream(B) = all nodes that transitively depend on B
                  = nodes that break when B changes
                  = predecessors-reachable set in the DiGraph.
    upstream(A)   = all nodes that A transitively depends on
                  = successors-reachable set.

Node kinds
----------
``"file"``
    Default.  A source file, identified by its repo-relative POSIX path
    (e.g. ``services/booking.py``).

``"function"``
    A callable defined inside a Python file.  Path format:
    ``"relative/file.py::function_name"`` for top-level functions, or
    ``"relative/file.py::ClassName.method_name"`` for methods.

Edge dep_kinds
--------------
``"import"``
    Default.  The *from* node imports the *to* node (file → file, or
    function → function across files).

``"contains"``
    A ``"file"`` node contains a ``"function"`` node
    (file → function).  Used in the detailed/function-level graph to
    link each function back to the file that defines it.

``"calls"``
    A function node calls another function node (within the same file or
    resolved cross-file via import edges).
"""

from __future__ import annotations

import re
from io import StringIO

import networkx as nx


class DependencyGraph:
    """Thin wrapper around :class:`networkx.DiGraph` for dependency tracking."""

    def __init__(self) -> None:
        self._g: nx.DiGraph = nx.DiGraph()

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def add_node(self, path: str, node_kind: str = "file", **attrs) -> None:
        """Add (or update) a node.  Idempotent — calling twice is harmless."""
        self._g.add_node(path, node_kind=node_kind, **attrs)

    def add_edge(self, from_path: str, to_path: str, dep_kind: str = "import") -> None:
        """Add an edge *from_path* → *to_path* (from_path imports to_path).

        Auto-creates either endpoint node if it does not already exist.
        Idempotent.
        """
        if from_path not in self._g:
            self.add_node(from_path)
        if to_path not in self._g:
            self.add_node(to_path)
        self._g.add_edge(from_path, to_path, dep_kind=dep_kind)

    # ------------------------------------------------------------------
    # Traversal
    # ------------------------------------------------------------------

    def downstream(self, node_path: str) -> set[str]:
        """Return all nodes that transitively depend on *node_path*.

        Follows incoming edges (predecessors) in the digraph.
        *node_path* itself is excluded from the result.
        Returns an empty set when *node_path* is not in the graph.
        """
        if node_path not in self._g:
            return set()
        visited: set[str] = set()
        queue: list[str] = list(self._g.predecessors(node_path))
        while queue:
            node = queue.pop()
            if node in visited:
                continue
            visited.add(node)
            queue.extend(self._g.predecessors(node))
        return visited

    def downstream_filtered(
        self,
        node_path: str,
        dep_kinds: set[str],
    ) -> set[str]:
        """Like :meth:`downstream` but only follows edges whose ``dep_kind``
        is in *dep_kinds*.

        Useful for function-level impact analysis where you want to traverse
        only ``"calls"`` and ``"contains"`` edges and not bleed across
        ``"import"`` edges that connect file nodes.
        """
        visited: set[str] = set()
        queue: list[str] = [
            u
            for u in self._g.predecessors(node_path)
            if self._g.edges[u, node_path].get("dep_kind") in dep_kinds
        ]
        while queue:
            node = queue.pop()
            if node in visited:
                continue
            visited.add(node)
            queue.extend(
                u
                for u in self._g.predecessors(node)
                if self._g.edges[u, node].get("dep_kind") in dep_kinds
            )
        return visited

    def upstream(self, node_path: str) -> set[str]:
        """Return all nodes that *node_path* transitively depends on.

        Follows outgoing edges (successors) in the digraph.
        *node_path* itself is excluded from the result.
        """
        visited: set[str] = set()
        queue: list[str] = list(self._g.successors(node_path))
        while queue:
            node = queue.pop()
            if node in visited:
                continue
            visited.add(node)
            queue.extend(self._g.successors(node))
        return visited

    # ------------------------------------------------------------------
    # Serialisation / introspection
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Serialise the graph to a plain dict with ``nodes`` and ``edges`` lists."""
        nodes = [{"path": n, **self._g.nodes[n]} for n in self._g.nodes]
        edges = [
            {"from": u, "to": v, **self._g.edges[u, v]}
            for u, v in self._g.edges
        ]
        return {"nodes": nodes, "edges": edges}

    # ------------------------------------------------------------------
    # Visualisation
    # ------------------------------------------------------------------

    def to_mermaid(self) -> str:
        """Return a Mermaid ``graph TD`` flowchart of the dependency graph.

        Each file becomes a node labelled with its path.  An edge
        ``A --> B`` means *A imports B*.  Node IDs are sanitised so they
        are valid Mermaid identifiers (slashes and dots replaced with
        underscores); the original path is used as the display label.

        Returns a complete Mermaid diagram string, e.g.::

            graph TD
                services_booking_py["services/booking.py"]
                models_py["models.py"]
                services_booking_py --> models_py
        """
        def _node_id(path: str) -> str:
            # Replace characters that break Mermaid identifiers.
            return re.sub(r"[^A-Za-z0-9_]", "_", path)

        lines: list[str] = ["graph TD"]

        # Declare every node with a quoted display label so paths with
        # slashes and dots render correctly.
        for node in sorted(self._g.nodes):
            nid = _node_id(node)
            lines.append(f'    {nid}["{node}"]')

        # Emit edges in sorted order for deterministic output.
        for u, v in sorted(self._g.edges):
            lines.append(f"    {_node_id(u)} --> {_node_id(v)}")

        return "\n".join(lines)

    def to_dot(self) -> str:
        """Return a Graphviz DOT representation of the dependency graph.

        Uses networkx's built-in ``nx.drawing.nx_pydot`` module when
        *pydot* is available; otherwise falls back to a hand-rolled DOT
        serialiser that has no extra dependencies.

        The returned string can be piped directly to ``dot -Tsvg`` or
        ``dot -Tpng``.
        """
        try:
            import pydot  # noqa: F401 — availability check only
            from networkx.drawing.nx_pydot import to_pydot

            pydot_graph = to_pydot(self._g)
            pydot_graph.set_name("dependency_graph")
            return pydot_graph.to_string()
        except ImportError:
            pass

        # Fallback: hand-rolled DOT serialiser (no extra deps needed).
        buf = StringIO()
        buf.write("digraph dependency_graph {\n")
        buf.write('    node [shape=box fontname="Helvetica"];\n')
        for node in sorted(self._g.nodes):
            # Quote node names so paths with slashes/dots are valid DOT IDs.
            safe = node.replace("\\", "\\\\").replace('"', '\\"')
            buf.write(f'    "{safe}";\n')
        for u, v in sorted(self._g.edges):
            su = u.replace("\\", "\\\\").replace('"', '\\"')
            sv = v.replace("\\", "\\\\").replace('"', '\\"')
            buf.write(f'    "{su}" -> "{sv}";\n')
        buf.write("}\n")
        return buf.getvalue()

    def __len__(self) -> int:
        """Return the number of nodes in the graph."""
        return self._g.number_of_nodes()

    def node_count(self) -> int:
        """Return the number of nodes in the graph."""
        return len(self._g.nodes)
