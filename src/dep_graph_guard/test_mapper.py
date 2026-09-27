"""test_mapper.py — maps source file nodes to their test files.

Reads optional ``dep-graph-guard.json`` from the repo root for config overrides.
Falls back to built-in convention patterns when the config file is absent.

Convention patterns are applied via :func:`fnmatch.fnmatch` against the
*basename* of each node path for filename patterns, and against the full
repo-relative path for directory-based patterns (``test/``, ``tests/``,
``__tests__/``).

A test file "covers" a source node when EITHER condition holds:
1. **Graph-edge coverage** — the test file is a predecessor of the source node
   in the dependency graph (i.e. the test imports the source file, directly or
   transitively via one hop is sufficient — we check direct predecessors only
   for efficiency).
2. **Naming-convention coverage** — the test file's stem matches one of the
   recognised naming templates derived from the source file's stem, e.g.
   ``test_{stem}.py``, ``{stem}_test.py``, ``{stem}.test.ts``, etc.
"""

from __future__ import annotations

import fnmatch
import json
import os
from pathlib import Path, PurePosixPath
from typing import Any

from dep_graph_guard.graph import DependencyGraph

# ---------------------------------------------------------------------------
# Built-in convention patterns (applied to the *basename* of each node)
# ---------------------------------------------------------------------------

_BUILTIN_FILENAME_PATTERNS: list[str] = [
    # Python
    "test_*.py",
    "*_test.py",
    # JS / TS
    "*.test.ts",
    "*.test.js",
    "*.spec.ts",
    "*.spec.js",
    "*.test.tsx",
    "*.test.jsx",
    # Java
    "*Test.java",
    "*Tests.java",
    "*Spec.java",
]

# Path *segments* whose presence (anywhere in the path) marks a test file.
_BUILTIN_TEST_DIRS: list[str] = ["test", "tests", "__tests__"]

# Naming-convention templates used for coverage detection.
# Each is a (format_string, extension_check) where the format string uses
# ``{stem}`` as the placeholder.  Extension check is applied to the test
# file basename to avoid false matches across languages.
_COVERAGE_TEMPLATES: list[str] = [
    "test_{stem}.py",
    "{stem}_test.py",
    "{stem}.test.ts",
    "{stem}.test.js",
    "{stem}.spec.ts",
    "{stem}.spec.js",
    "{stem}.test.tsx",
    "{stem}.test.jsx",
    "{stem}Test.java",
    "{stem}Tests.java",
    "{stem}Spec.java",
]


class TestMapper:
    """Identifies test nodes in a :class:`~dep_graph_guard.graph.DependencyGraph`
    and maps affected source nodes to the tests that cover them.
    """

    def __init__(self, repo_path: str) -> None:
        self._repo_path = repo_path

        # Start from built-in defaults.
        self._filename_patterns: list[str] = list(_BUILTIN_FILENAME_PATTERNS)
        self._test_dirs: list[str] = list(_BUILTIN_TEST_DIRS)

        # Merge with optional repo-level config.
        config = self._load_config()
        self._filename_patterns.extend(config.get("test_patterns", []))
        self._test_dirs.extend(config.get("test_dirs", []))

    # ------------------------------------------------------------------
    # Config loading
    # ------------------------------------------------------------------

    def _load_config(self) -> dict[str, Any]:
        config_path = Path(self._repo_path) / "dep-graph-guard.json"
        if config_path.exists():
            try:
                with config_path.open(encoding="utf-8") as fh:
                    return json.load(fh)
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def find_test_nodes(self, graph: DependencyGraph) -> set[str]:
        """Return all nodes in *graph* that are identified as test files."""
        test_nodes: set[str] = set()
        for node in graph.to_dict()["nodes"]:
            path_str: str = node["path"]
            if self._is_test_node(path_str):
                test_nodes.add(path_str)
        return test_nodes

    def map_to_tests(self, affected_nodes: list[str], graph: DependencyGraph) -> dict:
        """Map *affected_nodes* to the test files that cover them.

        Returns a dict with keys:
        - ``tests_to_run``: sorted list of covering test files.
        - ``uncovered_nodes``: nodes with no covering test.
        - ``coverage_summary``: ``{"covered": N, "uncovered": M}``.
        """
        test_nodes = self.find_test_nodes(graph)
        # Build a lookup: source node → set of direct predecessors (importers).
        graph_dict = graph.to_dict()
        predecessors: dict[str, set[str]] = {}
        for edge in graph_dict["edges"]:
            predecessors.setdefault(edge["to"], set()).add(edge["from"])

        tests_to_run: set[str] = set()
        uncovered_nodes: list[str] = []

        for node in affected_nodes:
            covering: set[str] = set()

            # 1. Graph-edge coverage: test files that directly import this node.
            for pred in predecessors.get(node, set()):
                if pred in test_nodes:
                    covering.add(pred)

            # 2. Naming-convention coverage.
            node_stem = Path(node).stem
            for test in test_nodes:
                test_basename = os.path.basename(test)
                for template in _COVERAGE_TEMPLATES:
                    if test_basename == template.format(stem=node_stem):
                        covering.add(test)
                        break

            if covering:
                tests_to_run.update(covering)
            else:
                uncovered_nodes.append(node)

        covered_count = len(affected_nodes) - len(uncovered_nodes)
        return {
            "tests_to_run": sorted(tests_to_run),
            "uncovered_nodes": sorted(uncovered_nodes),
            "coverage_summary": {
                "covered": covered_count,
                "uncovered": len(uncovered_nodes),
            },
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_test_node(self, path_str: str) -> bool:
        """Return True if *path_str* matches any test-detection heuristic."""
        basename = os.path.basename(path_str)

        # Filename pattern match.
        for pattern in self._filename_patterns:
            if fnmatch.fnmatch(basename, pattern):
                return True

        # Directory-segment match: any path segment equals a test dir name.
        parts = PurePosixPath(path_str.replace("\\", "/")).parts
        for part in parts[:-1]:  # exclude the filename itself
            if part in self._test_dirs:
                return True

        return False
