"""Tests for the Python import parser."""

import os
from pathlib import Path

import pytest

from dep_graph_guard.parsers.python_parser import parse

# Path to the small fixture repo used by all tests in this module.
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "python_sample"


def _edge_set(repo_path: Path) -> set[tuple[str, str]]:
    return set(parse(str(repo_path)))


class TestBasicEdges:
    """Expected edges are present for the python_sample fixture."""

    def test_main_imports_utils_helper(self):
        edges = _edge_set(FIXTURE_DIR)
        assert ("main.py", "utils/helper.py") in edges, (
            f"Expected ('main.py', 'utils/helper.py') in edges, got:\n{sorted(edges)}"
        )

    def test_main_imports_utils_init(self):
        edges = _edge_set(FIXTURE_DIR)
        assert ("main.py", "utils/__init__.py") in edges, (
            f"Expected ('main.py', 'utils/__init__.py') in edges, got:\n{sorted(edges)}"
        )


class TestStdlibFiltered:
    """Stdlib imports must NOT appear in the output."""

    def test_os_import_is_not_returned(self):
        edges = _edge_set(FIXTURE_DIR)
        importers = {imp for imp, _ in edges}
        # "import os" in main.py — the imported side should never be "os.py" or similar
        imported_targets = {imp for _, imp in edges}
        # There should be no edge whose target looks like a stdlib module path
        # (stdlib files are not inside the fixture repo, so they won't resolve).
        # Specifically no edge with an 'os' target.
        assert all(
            not tgt.startswith("os") for tgt in imported_targets
        ), f"Unexpected stdlib edge found: {imported_targets}"

    def test_only_repo_local_files_returned(self):
        edges = _edge_set(FIXTURE_DIR)
        repo_files = {
            str(p.relative_to(FIXTURE_DIR)).replace(os.sep, "/")
            for p in FIXTURE_DIR.rglob("*.py")
        }
        for _importer, imported in edges:
            assert imported in repo_files, (
                f"Imported target '{imported}' is not a repo-local file. "
                f"All repo files: {repo_files}"
            )


class TestSyntaxErrorGraceful:
    """A file with a syntax error must not crash parse(); a warning is emitted instead."""

    def test_no_crash_on_bad_syntax_file(self, capsys):
        # bad_syntax.py is in the fixture dir; parse() must complete without raising.
        edges = _edge_set(FIXTURE_DIR)
        captured = capsys.readouterr()
        # A warning should have been written to stderr.
        assert "bad_syntax.py" in captured.err, (
            "Expected a warning about bad_syntax.py on stderr, got: " + repr(captured.err)
        )
        # The rest of the graph is still present.
        assert ("main.py", "utils/helper.py") in edges


class TestRelativeImports:
    """Relative imports resolve correctly."""

    def test_relative_import_in_package(self, tmp_path: Path):
        """from . import sibling  inside a package resolves to sibling.py."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "sibling.py").write_text("VALUE = 42\n")
        (pkg / "consumer.py").write_text("from . import sibling\n")

        edges = set(parse(str(tmp_path)))
        assert ("pkg/consumer.py", "pkg/sibling.py") in edges, (
            f"Relative import edge not found. Got: {sorted(edges)}"
        )

    def test_relative_import_from_submodule(self, tmp_path: Path):
        """from ..utils import helper  resolves upward correctly."""
        (tmp_path / "utils").mkdir()
        (tmp_path / "utils" / "__init__.py").write_text("")
        (tmp_path / "utils" / "helper.py").write_text("X = 1\n")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "__init__.py").write_text("")
        (sub / "consumer.py").write_text("from ..utils import helper\n")

        edges = set(parse(str(tmp_path)))
        assert ("sub/consumer.py", "utils/helper.py") in edges, (
            f"Cross-package relative import edge not found. Got: {sorted(edges)}"
        )


class TestExcludedDirs:
    """Files inside excluded directories must never appear in the output."""

    def test_venv_dir_is_skipped(self, tmp_path: Path):
        """A .venv directory is not traversed."""
        # A real source file
        (tmp_path / "app.py").write_text("import utils\n")
        (tmp_path / "utils.py").write_text("X = 1\n")

        # A .py file inside .venv — must be invisible to the parser
        venv = tmp_path / ".venv" / "lib" / "site-packages" / "pkg"
        venv.mkdir(parents=True)
        (venv / "thing.py").write_text("import app\n")

        edges = set(parse(str(tmp_path)))

        # The venv file must not appear as an importer or imported target
        all_paths = {p for pair in edges for p in pair}
        for p in all_paths:
            assert not p.startswith(".venv/"), (
                f"Path from .venv/ leaked into edges: {p!r}"
            )

    def test_pycache_dir_is_skipped(self, tmp_path: Path):
        """__pycache__ directories are not traversed."""
        (tmp_path / "mod.py").write_text("X = 1\n")
        cache = tmp_path / "__pycache__"
        cache.mkdir()
        (cache / "mod.cpython-311.pyc").write_bytes(b"")  # not a .py, but dir still skipped

        # No crash and the cache dir produced no nodes
        edges = set(parse(str(tmp_path)))
        all_paths = {p for pair in edges for p in pair}
        for p in all_paths:
            assert not p.startswith("__pycache__/"), (
                f"Path from __pycache__/ leaked: {p!r}"
            )

    def test_node_modules_dir_is_skipped(self, tmp_path: Path):
        """node_modules directories are not traversed (shared constant)."""
        (tmp_path / "app.py").write_text("X = 1\n")
        nm = tmp_path / "node_modules" / "some_pkg"
        nm.mkdir(parents=True)
        (nm / "index.py").write_text("import app\n")

        edges = set(parse(str(tmp_path)))
        all_paths = {p for pair in edges for p in pair}
        for p in all_paths:
            assert not p.startswith("node_modules/"), (
                f"Path from node_modules/ leaked: {p!r}"
            )
