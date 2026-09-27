"""Tests for dep_graph_guard.parsers.java_parser."""

from __future__ import annotations

import os
import pathlib
import pytest

from dep_graph_guard.parsers.java_parser import parse

FIXTURE_DIR = pathlib.Path(__file__).parent / "fixtures" / "java_sample"


def test_expected_edge_present():
    """parse() must return the edge from Main.java to Helper.java."""
    edges = parse(str(FIXTURE_DIR))
    assert (
        "com/example/Main.java",
        "com/example/util/Helper.java",
    ) in edges


def test_third_party_import_not_returned():
    """java.util.List is a JDK class — it must NOT appear as an edge."""
    edges = parse(str(FIXTURE_DIR))
    imported_files = {imp for _, imp in edges}
    # No edge target should look like a JDK path
    for imp in imported_files:
        assert not imp.startswith("java/"), (
            f"JDK import resolved to a file path unexpectedly: {imp}"
        )


def test_wildcard_import_does_not_crash(capsys):
    """Wildcard imports (com.example.util.*) must be skipped without raising."""
    # parse() must complete without exception; wildcard warning goes to stderr
    edges = parse(str(FIXTURE_DIR))
    captured = capsys.readouterr()
    assert "wildcard" in captured.err.lower(), (
        "Expected a wildcard-skip warning on stderr"
    )


def test_string_utils_not_a_dependent_of_main():
    """StringUtils was never imported by Main — it must not appear as a dependency."""
    edges = parse(str(FIXTURE_DIR))
    # No edge should point FROM Main.java TO StringUtils.java
    assert (
        "com/example/Main.java",
        "com/example/util/StringUtils.java",
    ) not in edges


def test_return_type_is_list_of_tuples():
    """parse() must return a list of 2-tuples of strings."""
    edges = parse(str(FIXTURE_DIR))
    assert isinstance(edges, list)
    for edge in edges:
        assert isinstance(edge, tuple) and len(edge) == 2
        assert isinstance(edge[0], str) and isinstance(edge[1], str)


def test_paths_are_posix_relative():
    """All returned paths must be repo-relative POSIX strings (no backslashes)."""
    edges = parse(str(FIXTURE_DIR))
    for src, dst in edges:
        assert "\\" not in src, f"Non-POSIX path in importer: {src}"
        assert "\\" not in dst, f"Non-POSIX path in imported: {dst}"
        assert not pathlib.PurePosixPath(src).is_absolute()
        assert not pathlib.PurePosixPath(dst).is_absolute()


def test_target_dir_is_skipped(tmp_path):
    """Maven target/ build-output directory is not traversed."""
    # Minimal source tree
    src = tmp_path / "com" / "example"
    src.mkdir(parents=True)
    (src / "App.java").write_text(
        "package com.example;\npublic class App {}\n"
    )

    # Compiled class mirrored as .java inside target/ (unusual but should be skipped)
    tgt = tmp_path / "target" / "com" / "example"
    tgt.mkdir(parents=True)
    (tgt / "App.java").write_text(
        "package com.example;\npublic class App {}\n"
    )

    edges = parse(str(tmp_path))
    all_paths = {p for pair in edges for p in pair}
    for p in all_paths:
        assert not p.startswith("target/"), (
            f"Path from target/ leaked: {p!r}"
        )


def test_build_dir_is_skipped(tmp_path):
    """build/ directory is not traversed."""
    src = tmp_path / "com" / "example"
    src.mkdir(parents=True)
    (src / "Util.java").write_text(
        "package com.example;\npublic class Util {}\n"
    )

    bld = tmp_path / "build" / "com" / "example"
    bld.mkdir(parents=True)
    (bld / "Util.java").write_text(
        "package com.example;\npublic class Util {}\n"
    )

    edges = parse(str(tmp_path))
    all_paths = {p for pair in edges for p in pair}
    for p in all_paths:
        assert not p.startswith("build/"), (
            f"Path from build/ leaked: {p!r}"
        )
