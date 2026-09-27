"""Tests for python_parser.parse_functions() — function-level graph extraction.

Covers:
* A simple call chain of 3 functions across 2 files.
* Method definitions and calls (class bodies).
* Calls to unresolved / external names are skipped without crashing.
* FunctionGraphResult structure (contains, function_nodes, calls fields).
* build_dependency_graph_detailed and analyze_change_impact(changed_functions=).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dep_graph_guard.parsers.python_parser import parse_functions


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


# ===========================================================================
# Cross-file 3-function call chain
#
#   utils.py   defines  helper()
#   main.py    defines  entry() which calls helper() (imported from utils)
#              defines  wrapper() which calls entry()
#
# Expected call edges:
#   main.py::entry   -> utils.py::helper   (cross-file, resolved via import)
#   main.py::wrapper -> main.py::entry     (same-file)
# ===========================================================================

@pytest.fixture()
def chain_repo(tmp_path: Path) -> Path:
    _write(tmp_path / "utils.py", "def helper():\n    return 42\n")
    _write(
        tmp_path / "main.py",
        "from utils import helper\n"
        "\n"
        "def entry():\n"
        "    return helper()\n"
        "\n"
        "def wrapper():\n"
        "    return entry()\n",
    )
    return tmp_path


class TestCrossFileCallChain:
    def test_function_nodes_present(self, chain_repo):
        result = parse_functions(str(chain_repo))
        assert "utils.py::helper" in result.function_nodes
        assert "main.py::entry" in result.function_nodes
        assert "main.py::wrapper" in result.function_nodes

    def test_contains_edges(self, chain_repo):
        result = parse_functions(str(chain_repo))
        contains_set = set(result.contains)
        assert ("utils.py", "utils.py::helper") in contains_set
        assert ("main.py", "main.py::entry") in contains_set
        assert ("main.py", "main.py::wrapper") in contains_set

    def test_same_file_call_edge(self, chain_repo):
        """wrapper() calls entry() in the same file."""
        result = parse_functions(str(chain_repo))
        assert ("main.py::wrapper", "main.py::entry") in result.calls

    def test_cross_file_call_edge(self, chain_repo):
        """entry() calls helper() imported from utils.py."""
        result = parse_functions(str(chain_repo))
        assert ("main.py::entry", "utils.py::helper") in result.calls

    def test_no_self_loops(self, chain_repo):
        """No function should have a call edge to itself."""
        result = parse_functions(str(chain_repo))
        for caller, callee in result.calls:
            assert caller != callee, f"Self-loop detected: {caller}"


# ===========================================================================
# Method definitions and calls
#
#   service.py defines class Greeter with say_hello() calling _build_msg()
#
# Expected:
#   contains: service.py -> service.py::Greeter.say_hello
#   contains: service.py -> service.py::Greeter._build_msg
#   calls:    service.py::Greeter.say_hello -> service.py::Greeter._build_msg
# ===========================================================================

@pytest.fixture()
def method_repo(tmp_path: Path) -> Path:
    _write(
        tmp_path / "service.py",
        "class Greeter:\n"
        "    def _build_msg(self, name: str) -> str:\n"
        "        return f'Hello, {name}'\n"
        "\n"
        "    def say_hello(self, name: str) -> None:\n"
        "        msg = self._build_msg(name)\n"
        "        print(msg)\n",
    )
    return tmp_path


class TestMethodCallEdges:
    def test_method_nodes_present(self, method_repo):
        result = parse_functions(str(method_repo))
        assert "service.py::Greeter.say_hello" in result.function_nodes
        assert "service.py::Greeter._build_msg" in result.function_nodes

    def test_method_contains_edges(self, method_repo):
        result = parse_functions(str(method_repo))
        contains_set = set(result.contains)
        assert ("service.py", "service.py::Greeter.say_hello") in contains_set
        assert ("service.py", "service.py::Greeter._build_msg") in contains_set

    def test_method_call_edge(self, method_repo):
        """say_hello calls _build_msg via self._build_msg()."""
        result = parse_functions(str(method_repo))
        # The attribute call ``self._build_msg(...)`` produces the bare name
        # ``_build_msg``, which resolves to the method in the same class.
        assert (
            "service.py::Greeter.say_hello",
            "service.py::Greeter._build_msg",
        ) in result.calls


# ===========================================================================
# Unresolved / external calls are skipped without crashing
#
#   external_calls.py calls print(), len(), datetime.now(), etc.
#   None of these should appear in the call edges.
# ===========================================================================

@pytest.fixture()
def external_repo(tmp_path: Path) -> Path:
    _write(
        tmp_path / "external_calls.py",
        "from datetime import datetime\n"
        "import os\n"
        "\n"
        "def do_stuff():\n"
        "    print('hello')\n"
        "    n = len([1, 2, 3])\n"
        "    t = datetime.now()\n"
        "    p = os.getcwd()\n"
        "    return n, t, p\n",
    )
    return tmp_path


class TestUnresolvedCallsSkipped:
    def test_no_crash(self, external_repo):
        """parse_functions must complete without raising."""
        result = parse_functions(str(external_repo))
        assert isinstance(result.calls, list)

    def test_function_node_present(self, external_repo):
        result = parse_functions(str(external_repo))
        assert "external_calls.py::do_stuff" in result.function_nodes

    def test_no_external_call_edges(self, external_repo):
        """Calls to print, len, datetime.now, os.getcwd must not produce edges."""
        result = parse_functions(str(external_repo))
        callees = {callee for _, callee in result.calls}
        for name in ("print", "len", "now", "getcwd"):
            # No callee ID should reference unresolved / stdlib names.
            assert not any(name in callee for callee in callees), (
                f"Unexpected call edge to external name {name!r}: {callees}"
            )

    def test_no_call_edges_at_all(self, external_repo):
        """With no local-repo imports, call edges must be empty."""
        result = parse_functions(str(external_repo))
        assert result.calls == []


# ===========================================================================
# Syntax error in one file does not prevent other files from being parsed
# ===========================================================================

class TestSyntaxErrorGraceful:
    def test_bad_file_skipped(self, tmp_path, capsys):
        _write(tmp_path / "good.py", "def ok(): pass\n")
        _write(tmp_path / "bad.py", "def broken(\n")  # unclosed paren

        result = parse_functions(str(tmp_path))
        # The good file must still be processed.
        assert "good.py::ok" in result.function_nodes
        # bad.py must not appear.
        assert not any("bad.py" in n for n in result.function_nodes)


# ===========================================================================
# build_dependency_graph_detailed (server-level integration)
# ===========================================================================

class TestBuildDependencyGraphDetailed:
    def test_stats_structure(self, chain_repo):
        import json
        from dep_graph_guard.server import build_dependency_graph_detailed

        data = json.loads(build_dependency_graph_detailed(str(chain_repo)))
        stats = data["stats"]
        assert stats["function_node_count"] >= 3
        assert stats["file_node_count"] >= 2
        assert stats["edge_counts_by_kind"].get("contains", 0) >= 3
        assert stats["edge_counts_by_kind"].get("calls", 0) >= 1

    def test_function_nodes_in_output(self, chain_repo):
        import json
        from dep_graph_guard.server import build_dependency_graph_detailed

        data = json.loads(build_dependency_graph_detailed(str(chain_repo)))
        node_paths = {n["path"] for n in data["nodes"]}
        assert "main.py::entry" in node_paths
        assert "main.py::wrapper" in node_paths
        assert "utils.py::helper" in node_paths

    def test_invalid_granularity_raises(self, chain_repo):
        from dep_graph_guard.server import build_dependency_graph_detailed

        with pytest.raises(ValueError, match="granularity"):
            build_dependency_graph_detailed(str(chain_repo), granularity="class")


# ===========================================================================
# analyze_change_impact with changed_functions= (server-level integration)
# ===========================================================================

class TestAnalyzeChangeImpactFunctionLevel:
    """Narrower blast radius when changed_functions is provided."""

    @pytest.fixture()
    def split_repo(self, tmp_path: Path) -> Path:
        """Two service files each importing one function from models.py.

        models.py:   get_user()   get_flight()
        service_a.py: uses get_user()
        service_b.py: uses get_flight()

        Changing get_user() at function level should only affect service_a,
        NOT service_b — unlike the file-level blast which catches both.
        """
        _write(
            tmp_path / "models.py",
            "def get_user(uid): return uid\n"
            "def get_flight(fid): return fid\n",
        )
        _write(
            tmp_path / "service_a.py",
            "from models import get_user\n"
            "def process_user(uid):\n"
            "    return get_user(uid)\n",
        )
        _write(
            tmp_path / "service_b.py",
            "from models import get_flight\n"
            "def process_flight(fid):\n"
            "    return get_flight(fid)\n",
        )
        return tmp_path

    def test_file_level_catches_both_services(self, split_repo):
        import json
        from dep_graph_guard.server import analyze_change_impact

        result = json.loads(
            analyze_change_impact(str(split_repo), ["models.py"])
        )
        affected = set(result["transitively_affected"])
        assert "service_a.py" in affected
        assert "service_b.py" in affected

    def test_function_level_is_narrower(self, split_repo):
        """changed_functions=get_user should not pull in service_b."""
        import json
        from dep_graph_guard.server import analyze_change_impact

        result = json.loads(
            analyze_change_impact(
                str(split_repo),
                changed_files=["models.py"],
                changed_functions=["models.py::get_user"],
            )
        )
        fi = result["function_impact"]
        func_affected = set(fi["transitively_affected"])
        # service_a's process_user calls get_user — must be in blast radius.
        assert "service_a.py::process_user" in func_affected
        # service_b never calls get_user — must NOT be in blast radius.
        assert not any("service_b" in n for n in func_affected), (
            f"service_b unexpectedly in function blast radius: {func_affected}"
        )

    def test_function_impact_key_absent_without_changed_functions(self, split_repo):
        import json
        from dep_graph_guard.server import analyze_change_impact

        result = json.loads(
            analyze_change_impact(str(split_repo), ["models.py"])
        )
        assert "function_impact" not in result
