"""
Python import parser for dep-graph-guard.

Edge direction convention: (importer_file, imported_file) where
``importer_file`` depends on ``imported_file``.  Both values are
repo-relative POSIX path strings (e.g. ``src/foo/bar.py``).

Only imports that resolve to an actual file inside *repo_path* are
returned.  Stdlib and third-party imports are silently skipped.

Function-level graph
--------------------
:func:`parse_functions` extends the analysis to function granularity.
It returns three lists of tuples that together form the detailed graph:

* **contains** edges — ``(file_path, func_id)`` where
  ``func_id = "file_path::func_name"`` or
  ``"file_path::ClassName.method_name"``.

* **file_nodes** — the set of distinct function-ID strings so callers
  can add them as ``node_kind="function"`` nodes.

* **calls** edges — ``(caller_func_id, callee_func_id)`` for calls that
  resolve either within the same file (same-file call graph) or
  cross-file via the existing import edges (cross-file call graph).
  Calls to unresolved / external names are silently skipped.
"""

import ast
import os
import sys
from pathlib import Path, PurePosixPath
from typing import NamedTuple

from dep_graph_guard.parsers import EXCLUDED_DIRS


def _resolve_module(module_parts: list[str], repo_root: Path) -> str | None:
    """Return a repo-relative POSIX path for *module_parts*, or None."""
    rel = Path(*module_parts)
    # Try foo/bar.py
    candidate_py = repo_root / rel.with_suffix(".py")
    if candidate_py.is_file():
        return PurePosixPath(candidate_py.relative_to(repo_root)).as_posix()
    # Try foo/bar/__init__.py
    candidate_init = repo_root / rel / "__init__.py"
    if candidate_init.is_file():
        return PurePosixPath(candidate_init.relative_to(repo_root)).as_posix()
    return None


def _edges_for_file(
    py_file: Path,
    repo_root: Path,
) -> list[tuple[str, str]]:
    """Return (importer, imported) edges found in *py_file*."""
    try:
        source = py_file.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(py_file))
    except SyntaxError as exc:
        print(
            f"dep-graph-guard: warning: skipping {py_file} — syntax error: {exc}",
            file=sys.stderr,
        )
        return []
    except Exception as exc:  # noqa: BLE001
        print(
            f"dep-graph-guard: warning: skipping {py_file} — {exc}",
            file=sys.stderr,
        )
        return []

    importer = PurePosixPath(py_file.relative_to(repo_root)).as_posix()
    # Package directory of the importer (used for relative import resolution)
    importer_pkg_dir = py_file.parent

    edges: list[tuple[str, str]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                # "import foo.bar.baz" — try full name, then progressively shorter
                parts = alias.name.split(".")
                # First try the full dotted path (foo/bar/baz.py or foo/bar/baz/__init__.py)
                resolved = _resolve_module(parts, repo_root)
                if resolved is None and len(parts) > 1:
                    # Also try just the top-level package (foo/__init__.py)
                    resolved = _resolve_module(parts[:1], repo_root)
                if resolved is not None:
                    edges.append((importer, resolved))

        elif isinstance(node, ast.ImportFrom):
            level = node.level  # 0 = absolute, 1 = from . , 2 = from ..
            module = node.module or ""

            if level == 0:
                # Absolute import: from foo.bar import baz
                if module:
                    parts = module.split(".")
                    resolved = _resolve_module(parts, repo_root)
                    if resolved is not None:
                        edges.append((importer, resolved))
                    # Also try each name as a sub-module: from foo import bar
                    # where bar might be foo/bar.py
                    for alias in node.names:
                        sub_parts = parts + [alias.name]
                        sub_resolved = _resolve_module(sub_parts, repo_root)
                        if sub_resolved is not None:
                            edges.append((importer, sub_resolved))
            else:
                # Relative import: walk up `level` directories from importer_pkg_dir
                base_dir = importer_pkg_dir
                for _ in range(level - 1):
                    base_dir = base_dir.parent

                if module:
                    module_parts = module.split(".")
                    candidate_dir = base_dir.joinpath(*module_parts)
                    # Try base_dir/foo/bar.py
                    candidate_py = candidate_dir.with_suffix(".py")
                    if candidate_py.is_file():
                        edges.append(
                            (importer, PurePosixPath(candidate_py.relative_to(repo_root)).as_posix())
                        )
                    else:
                        # Try base_dir/foo/bar/__init__.py
                        candidate_init = candidate_dir / "__init__.py"
                        if candidate_init.is_file():
                            edges.append(
                                (importer, PurePosixPath(candidate_init.relative_to(repo_root)).as_posix())
                            )
                    # Also try each imported name as a sub-module of the package
                    # e.g. "from ..utils import helper" → base_dir/utils/helper.py
                    for alias in node.names:
                        sub_candidate_py = (candidate_dir / alias.name).with_suffix(".py")
                        if sub_candidate_py.is_file():
                            edges.append(
                                (importer, PurePosixPath(sub_candidate_py.relative_to(repo_root)).as_posix())
                            )
                        else:
                            sub_candidate_init = candidate_dir / alias.name / "__init__.py"
                            if sub_candidate_init.is_file():
                                edges.append(
                                    (importer, PurePosixPath(sub_candidate_init.relative_to(repo_root)).as_posix())
                                )
                else:
                    # "from . import name" — each name may be a submodule
                    for alias in node.names:
                        sub_parts = [alias.name]
                        candidate_py = (base_dir / alias.name).with_suffix(".py")
                        if candidate_py.is_file():
                            edges.append(
                                (importer, PurePosixPath(candidate_py.relative_to(repo_root)).as_posix())
                            )
                        else:
                            candidate_init = base_dir / alias.name / "__init__.py"
                            if candidate_init.is_file():
                                edges.append(
                                    (importer, PurePosixPath(candidate_init.relative_to(repo_root)).as_posix())
                                )

    return edges


def parse(repo_path: str) -> list[tuple[str, str]]:
    """Walk all ``.py`` files in *repo_path* and return import edges.

    Each edge is a ``(importer_file, imported_file)`` tuple of
    repo-relative POSIX path strings.  Only imports that resolve to a
    file inside the repo are returned; stdlib/third-party imports are
    skipped silently.
    """
    repo_root = Path(repo_path).resolve()
    edges: list[tuple[str, str]] = []

    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]
        for filename in filenames:
            if filename.endswith(".py"):
                py_file = Path(dirpath) / filename
                edges.extend(_edges_for_file(py_file, repo_root))

    return edges


# ---------------------------------------------------------------------------
# Function-level graph
# ---------------------------------------------------------------------------

class FunctionGraphResult(NamedTuple):
    """Return type of :func:`parse_functions`."""

    contains: list[tuple[str, str]]
    """``(file_path, func_id)`` — file contains this function."""

    function_nodes: list[str]
    """All function-node IDs (``"file.py::name"`` strings)."""

    calls: list[tuple[str, str]]
    """``(caller_func_id, callee_func_id)`` — intra- and cross-file calls."""


def _func_id(file_rel: str, qualifier: str) -> str:
    """Return the canonical function-node ID string."""
    return f"{file_rel}::{qualifier}"


def _collect_functions(
    tree: ast.AST,
    file_rel: str,
) -> dict[str, str]:
    """Walk *tree* and return a mapping of ``local_name -> func_id``.

    Covers top-level ``def`` / ``async def`` and methods inside classes.
    The *local_name* is what call-sites use within the same file
    (e.g. ``"book_flight"`` or ``"MyClass.my_method"``).

    For methods we register two keys:
    * ``"ClassName.method_name"`` → qualified func_id  (canonical)
    * ``"method_name"``          → qualified func_id  (for ``self.foo()`` resolution)

    The second registration is intentional: calls like ``self._build_msg()``
    are parsed as an Attribute call whose ``.attr`` is ``"_build_msg"``, so
    we need the bare name to resolve to the qualified method ID.  We track
    which bare method names have been claimed by class bodies so the
    top-level ``def`` walk does not re-register them as plain functions.
    """
    functions: dict[str, str] = {}
    # Bare method names already claimed by a class body — must not be
    # shadowed by top-level def registration.
    method_bare_names: set[str] = set()

    # First pass: collect class methods (gives them priority over same-named
    # top-level functions, which would be unusual but possible).
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            class_name = node.name
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    qualified = f"{class_name}.{item.name}"
                    qualified_id = _func_id(file_rel, qualified)
                    functions[qualified] = qualified_id
                    # Register bare name → qualified id for self.foo() resolution.
                    functions[item.name] = qualified_id
                    method_bare_names.add(item.name)

    # Second pass: collect top-level functions, skipping names already owned
    # by a class-body method to avoid duplicate / conflicting registrations.
    for node in tree.body:  # type: ignore[attr-defined]
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name not in method_bare_names:
                functions[node.name] = _func_id(file_rel, node.name)

    return functions


def _collect_calls_in_func(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[str]:
    """Return the raw called names inside *func_node* (best-effort)."""
    called: list[str] = []
    for node in ast.walk(func_node):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name):
                called.append(fn.id)
            elif isinstance(fn, ast.Attribute):
                # ``obj.method()`` — record ``method`` only (strip receiver).
                called.append(fn.attr)
    return called


def _functions_for_file(
    py_file: Path,
    repo_root: Path,
    # ``import_map[name] -> file_rel`` built from the file-level import edges
    import_map: dict[str, str],
) -> tuple[
    list[tuple[str, str]],   # contains edges
    list[str],               # function node IDs defined in this file
    list[tuple[str, str]],   # calls edges
]:
    """Extract function nodes and call edges from a single Python file."""
    try:
        source = py_file.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(py_file))
    except SyntaxError:
        return [], [], []
    except Exception:  # noqa: BLE001
        return [], [], []

    file_rel = PurePosixPath(py_file.relative_to(repo_root)).as_posix()

    # Map local_name -> func_id for every function defined in this file.
    local_funcs = _collect_functions(tree, file_rel)

    contains: list[tuple[str, str]] = []
    func_nodes: list[str] = []

    # De-duplicate: prefer the qualified name (ClassName.method) over the bare
    # method alias we also registered for call-site matching.
    seen_ids: set[str] = set()
    for func_id_val in local_funcs.values():
        if func_id_val not in seen_ids:
            seen_ids.add(func_id_val)
            contains.append((file_rel, func_id_val))
            func_nodes.append(func_id_val)

    # Build the call edges.
    # We need to walk the AST class-aware so we know which function
    # definition we're inside.
    calls: list[tuple[str, str]] = []

    def _visit_callable(
        func_def: ast.FunctionDef | ast.AsyncFunctionDef,
        caller_id: str,
    ) -> None:
        for called_name in _collect_calls_in_func(func_def):
            # 1. Same-file resolution.
            if called_name in local_funcs:
                callee_id = local_funcs[called_name]
                if callee_id != caller_id:
                    calls.append((caller_id, callee_id))
                continue

            # 2. Cross-file resolution via import_map.
            if called_name in import_map:
                target_file = import_map[called_name]
                callee_id = _func_id(target_file, called_name)
                calls.append((caller_id, callee_id))
                continue

            # 3. Unresolved — skip silently (same policy as file-level parser).

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    qualified = f"{node.name}.{item.name}"
                    caller_id = _func_id(file_rel, qualified)
                    _visit_callable(item, caller_id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            caller_id = _func_id(file_rel, node.name)
            _visit_callable(node, caller_id)

    return contains, func_nodes, calls


def _build_import_map(
    file_rel: str,
    tree: ast.AST,
    repo_root: Path,
    py_file: Path,
) -> dict[str, str]:
    """Return ``{imported_name: target_file_rel}`` for the imports in *tree*.

    Only names that map to a file inside the repo are included (same
    filtering as the file-level parser).  The map is used for cross-file
    call resolution: if a file imports ``book_flight`` from
    ``services/booking.py``, calls to ``book_flight(...)`` in this file
    can be linked to ``services/booking.py::book_flight``.
    """
    import_map: dict[str, str] = {}
    importer_pkg_dir = py_file.parent

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            level = node.level
            module = node.module or ""

            target_file: str | None = None

            if level == 0 and module:
                parts = module.split(".")
                target_file = _resolve_module(parts, repo_root)
            elif level > 0:
                base_dir = importer_pkg_dir
                for _ in range(level - 1):
                    base_dir = base_dir.parent
                if module:
                    module_parts = module.split(".")
                    candidate_py = (base_dir / Path(*module_parts)).with_suffix(".py")
                    if candidate_py.is_file():
                        target_file = PurePosixPath(
                            candidate_py.relative_to(repo_root)
                        ).as_posix()

            if target_file is not None:
                for alias in node.names:
                    name = alias.asname if alias.asname else alias.name
                    import_map[name] = target_file

        elif isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                resolved = _resolve_module(parts, repo_root)
                if resolved is not None:
                    name = alias.asname if alias.asname else alias.name
                    import_map[name] = resolved

    return import_map


def parse_functions(repo_path: str) -> FunctionGraphResult:
    """Walk all ``.py`` files and return the function-level graph.

    Returns a :class:`FunctionGraphResult` with:

    ``contains``
        List of ``(file_path, func_id)`` tuples — one per function
        definition, linking a file node to its function node.

    ``function_nodes``
        Flat list of all function-node ID strings.

    ``calls``
        List of ``(caller_func_id, callee_func_id)`` tuples for calls
        that resolve within the same file or across files via imports.
        Calls to external / unresolved names are silently omitted.

    Node-ID format
    ~~~~~~~~~~~~~~
    * Top-level function:  ``"services/booking.py::book_flight"``
    * Method:              ``"services/user.py::UserService.register"``
    """
    repo_root = Path(repo_path).resolve()

    all_contains: list[tuple[str, str]] = []
    all_func_nodes: list[str] = []
    all_calls: list[tuple[str, str]] = []

    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            py_file = Path(dirpath) / filename

            # Parse the AST once for both import-map and call extraction.
            try:
                source = py_file.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(source, filename=str(py_file))
            except SyntaxError as exc:
                print(
                    f"dep-graph-guard: warning: skipping {py_file} — "
                    f"syntax error: {exc}",
                    file=sys.stderr,
                )
                continue
            except Exception as exc:  # noqa: BLE001
                print(
                    f"dep-graph-guard: warning: skipping {py_file} — {exc}",
                    file=sys.stderr,
                )
                continue

            file_rel = PurePosixPath(py_file.relative_to(repo_root)).as_posix()
            import_map = _build_import_map(file_rel, tree, repo_root, py_file)

            contains, func_nodes, calls = _functions_for_file(
                py_file, repo_root, import_map
            )
            all_contains.extend(contains)
            all_func_nodes.extend(func_nodes)
            all_calls.extend(calls)

    return FunctionGraphResult(
        contains=all_contains,
        function_nodes=all_func_nodes,
        calls=all_calls,
    )
