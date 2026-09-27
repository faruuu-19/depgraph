"""
Java import parser for dep-graph-guard.

parse(repo_path) walks all .java files in repo_path, builds an index of
package+class → repo-relative file path, then for each import statement
attempts to resolve the FQN against that index.

Edge direction: (importer_file, imported_file) — both as repo-relative POSIX
path strings.

Wildcard imports (import com.example.*) are skipped with a stderr warning.
Static imports (import static com.example.Foo.METHOD) are handled by stripping
the leading "static" keyword and resolving the class-level FQN.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from dep_graph_guard.parsers import EXCLUDED_DIRS

_PACKAGE_RE = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.MULTILINE)
_IMPORT_RE = re.compile(r"^\s*import\s+(static\s+)?([\w.*]+)\s*;", re.MULTILINE)


def _build_index(repo_path: Path) -> dict[str, str]:
    """Return a mapping of fully-qualified class name → repo-relative POSIX path."""
    index: dict[str, str] = {}
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
        for fname in files:
            if not fname.endswith(".java"):
                continue
            abs_path = Path(root) / fname
            try:
                text = abs_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            pkg_match = _PACKAGE_RE.search(text)
            package = pkg_match.group(1) if pkg_match else ""

            class_name = abs_path.stem  # filename without .java
            fqn = f"{package}.{class_name}" if package else class_name

            rel_posix = abs_path.relative_to(repo_path).as_posix()
            index[fqn] = rel_posix
    return index


def parse(repo_path: str) -> list[tuple[str, str]]:
    """Walk all .java files under *repo_path* and return import edges.

    Returns a list of (importer_file, imported_file) tuples where both paths
    are repo-relative POSIX strings.  Only edges where the imported class is
    found within the repo are returned; JDK / third-party imports are silently
    skipped.
    """
    root = Path(repo_path)
    index = _build_index(root)
    edges: list[tuple[str, str]] = []

    for repo_rel, importer_posix in list(index.items()):
        abs_path = root / importer_posix
        try:
            text = abs_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        for m in _IMPORT_RE.finditer(text):
            is_static = bool(m.group(1))
            fqn = m.group(2)

            # Skip wildcard imports
            if fqn.endswith(".*"):
                print(
                    f"dep-graph-guard: skipping wildcard import '{fqn}' "
                    f"in {importer_posix}",
                    file=sys.stderr,
                )
                continue

            # For static imports, the last segment is the member name — strip it
            # so we can resolve to the enclosing class.
            if is_static:
                fqn = fqn.rsplit(".", 1)[0]

            imported_posix = index.get(fqn)
            if imported_posix is None:
                # Third-party or JDK — skip silently
                continue

            if imported_posix != importer_posix:
                edges.append((importer_posix, imported_posix))

    return edges
