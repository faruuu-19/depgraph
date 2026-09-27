"""dep-graph-guard MCP server entry point.

Uses the mcp 2.x MCPServer API (formerly FastMCP).
Six tools are registered:
  - build_dependency_graph
  - analyze_change_impact
  - get_required_tests
  - visualize_dependency_graph
  - build_dependency_graph_detailed
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import traceback
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from dep_graph_guard.graph import DependencyGraph
from dep_graph_guard.parsers import java_parser, js_ts_parser, python_parser
from dep_graph_guard.test_mapper import TestMapper

# ---------------------------------------------------------------------------
# MCP server instance
# ---------------------------------------------------------------------------

server = MCPServer("dep-graph-guard", version="0.1.0")

# ---------------------------------------------------------------------------
# Helper — kept at module level so e2e tests can call it directly
# ---------------------------------------------------------------------------

_JS_TS_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}


def _build_graph(repo_path: str) -> DependencyGraph:
    """Detect languages present in *repo_path* and parse only those.

    Returns a populated :class:`~dep_graph_guard.graph.DependencyGraph`.
    """
    root = Path(repo_path)
    has_python = False
    has_js_ts = False
    has_java = False

    for p in root.rglob("*"):
        if not p.is_file():
            continue
        ext = p.suffix.lower()
        if ext == ".py":
            has_python = True
        elif ext in _JS_TS_EXTENSIONS:
            has_js_ts = True
        elif ext == ".java":
            has_java = True
        if has_python and has_js_ts and has_java:
            break

    graph = DependencyGraph()
    edges: list[tuple[str, str]] = []

    if has_python:
        edges.extend(python_parser.parse(repo_path))
    if has_js_ts:
        edges.extend(js_ts_parser.parse(repo_path))
    if has_java:
        edges.extend(java_parser.parse(repo_path))

    for from_path, to_path in edges:
        graph.add_edge(from_path, to_path)

    return graph


# ---------------------------------------------------------------------------
# Tool handler functions — kept at module level for direct testability
# ---------------------------------------------------------------------------

def build_dependency_graph(repo_path: str) -> str:
    """Build and serialise the dependency graph for *repo_path*."""
    try:
        graph = _build_graph(repo_path)
        graph_dict = graph.to_dict()
        result = {
            "nodes": graph_dict["nodes"],
            "edges": graph_dict["edges"],
            "stats": {
                "node_count": len(graph_dict["nodes"]),
                "edge_count": len(graph_dict["edges"]),
                "repo_path": repo_path,
            },
        }
        return json.dumps(result)
    except Exception:
        traceback.print_exc(file=sys.stderr)
        raise


def analyze_change_impact(
    repo_path: str,
    changed_files: list[str],
    changed_functions: list[str] | None = None,
) -> str:
    """Call this BEFORE making any code change — do not skip this step.

    Returns the direct and transitive impact of *changed_files* so you know
    the full blast radius before touching anything.  Always pair this call
    with :func:`get_required_tests` using the returned affected nodes.

    Parameters
    ----------
    repo_path:
        Root directory of the repository to analyse.
    changed_files:
        Repo-relative file paths that were modified (e.g. ``["models.py"]``).
        File-level analysis is always performed.
    changed_functions:
        Optional list of function-node IDs in the format
        ``"file.py::func_name"`` or ``"file.py::Class.method"``.
        When provided, the detailed (function-level) graph is built via
        :func:`_build_detailed_graph` and the downstream impact set is
        computed starting from each named function node — giving a
        narrower, more precise blast radius than file-level analysis.

    The returned JSON always contains the file-level keys.  When
    *changed_functions* is provided an additional ``"function_impact"``
    key is included with the narrower function-level results.
    """
    try:
        graph = _build_graph(repo_path)
        graph_dict = graph.to_dict()

        # Build predecessor map for 1-hop lookup.
        predecessors: dict[str, set[str]] = {}
        for edge in graph_dict["edges"]:
            predecessors.setdefault(edge["to"], set()).add(edge["from"])

        directly_affected: set[str] = set()
        transitively_affected: set[str] = set()

        for f in changed_files:
            directly_affected.update(predecessors.get(f, set()))
            transitively_affected.update(graph.downstream(f))

        # Transitive already includes direct; keep them separate per spec.
        result: dict = {
            "changed_files": changed_files,
            "directly_affected": sorted(directly_affected),
            "transitively_affected": sorted(transitively_affected),
            "total_affected_count": len(transitively_affected),
        }

        # Function-level narrowing (optional).
        if changed_functions:
            detailed = _build_detailed_graph(repo_path)
            func_directly: set[str] = set()
            func_transitively: set[str] = set()
            # Only traverse "calls" and "contains" edges so that file-level
            # "import" edges do not bleed unrelated files into the blast radius.
            _FUNC_EDGE_KINDS = {"calls", "contains"}
            # Predecessor map restricted to function-graph edge kinds (1-hop).
            func_preds: dict[str, set[str]] = {}
            for u, v, data in detailed._g.edges(data=True):
                if data.get("dep_kind") in _FUNC_EDGE_KINDS:
                    func_preds.setdefault(v, set()).add(u)
            for fn in changed_functions:
                if fn in detailed._g:
                    func_directly.update(func_preds.get(fn, set()))
                    func_transitively.update(
                        detailed.downstream_filtered(fn, _FUNC_EDGE_KINDS)
                    )
            result["function_impact"] = {
                "changed_functions": changed_functions,
                "directly_affected": sorted(func_directly),
                "transitively_affected": sorted(func_transitively),
                "total_affected_count": len(func_transitively),
            }

        return json.dumps(result)
    except Exception:
        traceback.print_exc(file=sys.stderr)
        raise


def _build_detailed_graph(repo_path: str) -> "DependencyGraph":
    """Build a graph that includes both file-level and function-level nodes.

    The file-level import edges are present, plus for each Python file:
    * A ``"contains"`` edge from the file node to each function node it defines.
    * ``"calls"`` edges between function nodes (intra- and cross-file).

    This helper is module-level so tests can import it directly.
    """
    graph = _build_graph(repo_path)

    func_result = python_parser.parse_functions(repo_path)

    for func_id in func_result.function_nodes:
        graph.add_node(func_id, node_kind="function")

    for file_path, func_id in func_result.contains:
        graph.add_edge(file_path, func_id, dep_kind="contains")

    for caller_id, callee_id in func_result.calls:
        graph.add_edge(caller_id, callee_id, dep_kind="calls")

    return graph


def build_dependency_graph_detailed(
    repo_path: str,
    granularity: str = "function",
) -> str:
    """Build a dependency graph that includes function-level nodes for Python.

    Parameters
    ----------
    repo_path:
        Root directory of the repository to analyse.
    granularity:
        Currently only ``"function"`` is supported (default).  Reserved for
        future granularity levels (e.g. ``"class"``).

    Returns
    -------
    JSON string with the same ``nodes`` / ``edges`` / ``stats`` structure as
    :func:`build_dependency_graph`, plus:

    * ``"file"`` nodes for every source file (all languages).
    * ``"function"`` nodes (Python only) with IDs like
      ``"services/booking.py::book_flight"``.
    * ``"contains"`` edges from each file to the functions it defines.
    * ``"calls"`` edges between function nodes.
    * ``"import"`` edges between file nodes (unchanged from file-level graph).
    """
    try:
        if granularity != "function":
            raise ValueError(
                f"Unsupported granularity {granularity!r}. Only 'function' is currently supported."
            )

        graph = _build_detailed_graph(repo_path)
        graph_dict = graph.to_dict()

        # Counts broken down by node kind for easy inspection.
        file_count = sum(1 for n in graph_dict["nodes"] if n.get("node_kind") == "file")
        func_count = sum(1 for n in graph_dict["nodes"] if n.get("node_kind") == "function")
        edge_kinds: dict[str, int] = {}
        for e in graph_dict["edges"]:
            edge_kinds[e.get("dep_kind", "import")] = (
                edge_kinds.get(e.get("dep_kind", "import"), 0) + 1
            )

        result = {
            "nodes": graph_dict["nodes"],
            "edges": graph_dict["edges"],
            "stats": {
                "node_count": len(graph_dict["nodes"]),
                "file_node_count": file_count,
                "function_node_count": func_count,
                "edge_count": len(graph_dict["edges"]),
                "edge_counts_by_kind": edge_kinds,
                "repo_path": repo_path,
                "granularity": granularity,
            },
        }
        return json.dumps(result)
    except Exception:
        traceback.print_exc(file=sys.stderr)
        raise


def get_required_tests(repo_path: str, affected_nodes: list[str]) -> str:
    """Call this BEFORE making any code change — do not skip this step.

    Maps *affected_nodes* (from :func:`analyze_change_impact`) to the test
    files that cover them, and surfaces any nodes with no test coverage.
    Use the returned ``uncovered_nodes`` list to identify where new tests
    must be written before the change is complete.
    """
    try:
        graph = _build_graph(repo_path)
        mapper = TestMapper(repo_path)
        mapping = mapper.map_to_tests(affected_nodes, graph)
        return json.dumps(mapping)
    except Exception:
        traceback.print_exc(file=sys.stderr)
        raise


def visualize_dependency_graph(repo_path: str, output_format: str = "mermaid") -> str:
    """Return a visual representation of the dependency graph.

    Parameters
    ----------
    repo_path:
        Root directory of the repository to analyse.
    output_format:
        ``"mermaid"`` (default) — Mermaid ``graph TD`` flowchart syntax,
        renderable in any Markdown previewer or mermaid.live.
        ``"dot"`` — Graphviz DOT language, pipe to ``dot -Tsvg`` or open
        in any Graphviz viewer.

    Returns the diagram as a plain string.
    """
    try:
        graph = _build_graph(repo_path)

        fmt = output_format.strip().lower()
        if fmt == "mermaid":
            return graph.to_mermaid()
        if fmt == "dot":
            return graph.to_dot()

        raise ValueError(
            f"Unsupported output_format {output_format!r}. "
            "Valid options are 'mermaid' and 'dot'."
        )
    except Exception:
        traceback.print_exc(file=sys.stderr)
        raise


# ---------------------------------------------------------------------------
# Register tools with the MCP server
# ---------------------------------------------------------------------------

server.tool()(build_dependency_graph)
server.tool()(analyze_change_impact)
server.tool()(get_required_tests)
server.tool()(visualize_dependency_graph)
server.tool()(build_dependency_graph_detailed)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Console-script entry point.

    Runs over ``stdio`` by default (how an agent like Bob or Claude Code
    registers this server locally via ``mcp.json``). Set
    ``MCP_TRANSPORT=http`` to instead serve MCP over streamable-HTTP on
    ``0.0.0.0:$PORT`` (used for the hosted deployment).
    """
    transport = os.environ.get("MCP_TRANSPORT", "stdio").lower()
    if transport in ("http", "streamable-http"):
        port = int(os.environ.get("PORT", "8000"))
        print(f"dep-graph-guard MCP server starting on streamable-http :{port}", file=sys.stderr)
        server.run(transport="streamable-http", host="0.0.0.0", port=port, stateless_http=True)
    else:
        print("dep-graph-guard MCP server starting on stdio", file=sys.stderr)
        asyncio.run(server.run_stdio_async())
