"""
Tests for dep_graph_guard.parsers.js_ts_parser.
"""

import os
import pytest
from dep_graph_guard.parsers.js_ts_parser import parse

# Absolute path to the shared JS fixture directory.
FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "js_sample")


def _edges(fixture_path: str = FIXTURE_DIR) -> set[tuple[str, str]]:
    return set(parse(fixture_path))


class TestESModuleImports:
    """ES module `import ... from` syntax is captured."""

    def test_import_from_resolves_to_ts(self):
        """index.ts imports './lib/utils' which resolves to lib/utils.ts."""
        edges = _edges()
        assert ("index.ts", "lib/utils.ts") in edges

    def test_bare_specifier_not_returned(self):
        """Bare npm specifiers (e.g. 'react') must NOT appear in the results."""
        edges = _edges()
        imported_files = {imp for _, imp in edges}
        # None of the imported paths should look like an npm package name
        for path in imported_files:
            assert path.startswith("lib/") or path == "index.ts", (
                f"Unexpected imported path: {path!r}"
            )


class TestRequireCalls:
    """CommonJS require() calls are captured."""

    def test_require_resolves_to_js(self):
        """index.ts require('./lib/api') resolves to lib/api.js."""
        edges = _edges()
        assert ("index.ts", "lib/api.js") in edges


class TestExportFromSyntax:
    """export ... from syntax is captured."""

    def test_export_from_captured(self, tmp_path):
        """A file using `export { x } from './other'` produces an edge."""
        other = tmp_path / "other.ts"
        other.write_text("export const x = 1;\n")

        re_exporter = tmp_path / "re_exporter.ts"
        re_exporter.write_text("export { x } from './other';\n")

        edges = set(parse(str(tmp_path)))
        assert ("re_exporter.ts", "other.ts") in edges

    def test_export_star_from_captured(self, tmp_path):
        """A file using `export * from './other'` produces an edge."""
        other = tmp_path / "other.js"
        other.write_text("exports.y = 2;\n")

        barrel = tmp_path / "index.js"
        barrel.write_text("export * from './other';\n")

        edges = set(parse(str(tmp_path)))
        assert ("index.js", "other.js") in edges


class TestDynamicImport:
    """Static-string dynamic import() calls are captured."""

    def test_dynamic_import_captured(self, tmp_path):
        """import('./module') with a literal string is captured."""
        module = tmp_path / "module.ts"
        module.write_text("export default 42;\n")

        caller = tmp_path / "caller.ts"
        caller.write_text("const m = import('./module');\n")

        edges = set(parse(str(tmp_path)))
        assert ("caller.ts", "module.ts") in edges


class TestBareSpecifiersSkipped:
    """npm package names are always skipped."""

    def test_react_import_not_in_edges(self, tmp_path):
        source = tmp_path / "app.ts"
        source.write_text("import React from 'react';\n")
        edges = set(parse(str(tmp_path)))
        assert edges == set()

    def test_mixed_bare_and_relative(self, tmp_path):
        """Only the relative import is returned when both kinds are present."""
        local = tmp_path / "local.ts"
        local.write_text("export const a = 1;\n")

        source = tmp_path / "app.ts"
        source.write_text(
            "import React from 'react';\n"
            "import { a } from './local';\n"
        )
        edges = set(parse(str(tmp_path)))
        assert ("app.ts", "local.ts") in edges
        imported = {imp for _, imp in edges}
        assert "react" not in imported


class TestFileResolution:
    """Specifiers without explicit extensions are resolved correctly."""

    def test_resolves_ts_extension(self, tmp_path):
        target = tmp_path / "target.ts"
        target.write_text("export const v = 1;\n")

        caller = tmp_path / "caller.ts"
        caller.write_text("import { v } from './target';\n")

        edges = set(parse(str(tmp_path)))
        assert ("caller.ts", "target.ts") in edges

    def test_resolves_js_extension(self, tmp_path):
        target = tmp_path / "target.js"
        target.write_text("module.exports = {};\n")

        caller = tmp_path / "caller.ts"
        caller.write_text("const t = require('./target');\n")

        edges = set(parse(str(tmp_path)))
        assert ("caller.ts", "target.js") in edges

    def test_resolves_index_ts(self, tmp_path):
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "index.ts").write_text("export const v = 1;\n")

        caller = tmp_path / "caller.ts"
        caller.write_text("import { v } from './pkg';\n")

        edges = set(parse(str(tmp_path)))
        assert ("caller.ts", "pkg/index.ts") in edges


class TestExcludedDirs:
    """Files inside excluded directories are never traversed."""

    def test_node_modules_fully_skipped(self, tmp_path):
        """node_modules is skipped entirely, not just by bare-specifier filtering."""
        local = tmp_path / "local.ts"
        local.write_text("export const x = 1;\n")

        nm = tmp_path / "node_modules" / "pkg"
        nm.mkdir(parents=True)
        (nm / "index.ts").write_text("import { x } from '../../local';\n")

        edges = set(parse(str(tmp_path)))
        all_paths = {p for pair in edges for p in pair}
        for p in all_paths:
            assert not p.startswith("node_modules/"), (
                f"Path from node_modules/ leaked: {p!r}"
            )

    def test_dist_dir_is_skipped(self, tmp_path):
        """dist/ build-output directory is not traversed."""
        (tmp_path / "src.ts").write_text("export const x = 1;\n")
        dist = tmp_path / "dist"
        dist.mkdir()
        (dist / "src.js").write_text("const x = 1;\n")

        edges = set(parse(str(tmp_path)))
        all_paths = {p for pair in edges for p in pair}
        for p in all_paths:
            assert not p.startswith("dist/"), (
                f"Path from dist/ leaked: {p!r}"
            )
