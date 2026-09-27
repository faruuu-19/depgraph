"""
JS/TS import parser for dep-graph-guard.

Edge direction: (importer_file, imported_file) as repo-relative POSIX paths.

Handles:
  - import ... from 'SPEC' / "SPEC"
  - require('SPEC') / require("SPEC")
  - export ... from 'SPEC' / "SPEC"
  - Static import('SPEC') / import("SPEC") dynamic imports with literal strings

Only relative specifiers (starting with '.' or '..') are processed;
bare specifiers (npm packages) are silently skipped.

File resolution order for a specifier like './lib/utils':
  1. Exact path as given
  2. + .js
  3. + .ts
  4. + .jsx
  5. + .tsx
  6. + .mjs
  7. + .cjs
  8. /index.js
  9. /index.ts
"""

import os
import re
import sys
from pathlib import Path, PurePosixPath

from dep_graph_guard.parsers import EXCLUDED_DIRS

_JS_EXTENSIONS = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")

# Patterns for import specifiers — capture group 1 is the specifier string.
_PATTERNS = [
    # import ... from 'spec' or "spec"
    re.compile(r"""(?:^|[;\n])\s*import\b[^'"]*?from\s+(['"])([^'"]+)\1""", re.MULTILINE),
    # require('spec') or require("spec")
    re.compile(r"""\brequire\s*\(\s*(['"])([^'"]+)\1\s*\)"""),
    # export ... from 'spec' or "spec"
    re.compile(r"""(?:^|[;\n])\s*export\b[^'"]*?from\s+(['"])([^'"]+)\1""", re.MULTILINE),
    # static dynamic import('spec') or import("spec")
    re.compile(r"""\bimport\s*\(\s*(['"])([^'"]+)\1\s*\)"""),
]


def _resolve_specifier(base_dir: Path, specifier: str, repo_root: Path) -> str | None:
    """
    Resolve a relative specifier from base_dir to an actual file path.
    Returns the repo-relative POSIX path string, or None if unresolvable.
    """
    candidate_base = (base_dir / specifier).resolve()

    # Try exact path first, then with each extension, then /index.*
    candidates = [candidate_base]
    for ext in _JS_EXTENSIONS:
        candidates.append(candidate_base.with_suffix(ext))
    for idx_name in ("index.js", "index.ts", "index.jsx", "index.tsx", "index.mjs", "index.cjs"):
        candidates.append(candidate_base / idx_name)

    for candidate in candidates:
        if candidate.is_file():
            try:
                rel = candidate.relative_to(repo_root)
                return PurePosixPath(rel).as_posix()
            except ValueError:
                # Resolved outside the repo root — skip
                return None

    return None


def parse(repo_path: str) -> list[tuple[str, str]]:
    """
    Walk all JS/TS source files under repo_path and return a list of
    (importer_file, imported_file) pairs as repo-relative POSIX path strings.
    """
    repo_root = Path(repo_path).resolve()
    edges: list[tuple[str, str]] = []

    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]

        for filename in filenames:
            if not filename.endswith(_JS_EXTENSIONS):
                continue

            abs_path = Path(dirpath) / filename
            try:
                source = abs_path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                print(f"Warning: could not read {abs_path}: {exc}", file=sys.stderr)
                continue

            try:
                importer_rel = PurePosixPath(abs_path.relative_to(repo_root)).as_posix()
            except ValueError:
                continue

            base_dir = abs_path.parent

            seen_specs: set[str] = set()
            for pattern in _PATTERNS:
                for match in pattern.finditer(source):
                    # Group 2 is always the specifier (group 1 is the quote char)
                    specifier = match.group(2)
                    if specifier in seen_specs:
                        continue
                    seen_specs.add(specifier)

                    # Only process relative specifiers
                    if not specifier.startswith("."):
                        continue

                    resolved = _resolve_specifier(base_dir, specifier, repo_root)
                    if resolved is not None:
                        edges.append((importer_rel, resolved))

    return edges
