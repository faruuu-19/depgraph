"""CLI helper — generate a visual dependency graph from a repository.

Usage
-----
    # Mermaid diagram → graph.md  (open in any Markdown previewer)
    python scripts/visualize.py /path/to/repo

    # Explicit output path
    python scripts/visualize.py /path/to/repo -o deps.md

    # DOT format → deps.dot (then: dot -Tsvg deps.dot -o deps.svg)
    python scripts/visualize.py /path/to/repo -f dot -o deps.dot

    # DOT → SVG in one step (requires Graphviz 'dot' on PATH)
    python scripts/visualize.py /path/to/repo -f dot --svg deps.svg

The script can also be run without installing the package by invoking it
from the dep-graph-guard directory, which adds src/ to sys.path automatically.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

# Allow running without installing: add src/ to sys.path when the script is
# executed from inside the dep-graph-guard directory tree.
_HERE = Path(__file__).resolve().parent
_SRC = _HERE.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from dep_graph_guard.server import visualize_dependency_graph  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dot_to_svg(dot_source: str, svg_path: Path) -> None:
    """Render *dot_source* to an SVG file via the ``dot`` Graphviz binary."""
    dot_bin = shutil.which("dot")
    if dot_bin is None:
        print(
            "ERROR: 'dot' (Graphviz) not found on PATH. "
            "Install Graphviz or omit --svg to write the .dot file instead.",
            file=sys.stderr,
        )
        sys.exit(1)

    result = subprocess.run(
        [dot_bin, "-Tsvg", "-o", str(svg_path)],
        input=dot_source.encode(),
        capture_output=True,
    )
    if result.returncode != 0:
        print(
            f"ERROR: dot exited with code {result.returncode}:\n"
            f"{result.stderr.decode()}",
            file=sys.stderr,
        )
        sys.exit(1)


def _wrap_mermaid(diagram: str) -> str:
    """Wrap a raw Mermaid diagram in a Markdown fenced code block."""
    return f"```mermaid\n{diagram}\n```\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="visualize",
        description="Generate a visual dependency graph for a repository.",
    )
    p.add_argument(
        "repo_path",
        help="Root directory of the repository (or sub-project) to analyse.",
    )
    p.add_argument(
        "-f", "--format",
        dest="output_format",
        choices=["mermaid", "dot"],
        default="mermaid",
        help="Output format: 'mermaid' (default) or 'dot'.",
    )
    p.add_argument(
        "-o", "--output",
        dest="output_path",
        default=None,
        help=(
            "Output file path. Defaults to 'graph.md' for mermaid, "
            "'graph.dot' for dot."
        ),
    )
    p.add_argument(
        "--svg",
        dest="svg_path",
        default=None,
        metavar="SVG_FILE",
        help=(
            "Render DOT output directly to an SVG file using the 'dot' binary "
            "(implies --format dot). Graphviz must be installed."
        ),
    )
    return p


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # --svg implies dot format.
    if args.svg_path is not None:
        args.output_format = "dot"

    diagram = visualize_dependency_graph(args.repo_path, args.output_format)

    # --svg: render directly to SVG and exit.
    if args.svg_path is not None:
        svg_path = Path(args.svg_path)
        _dot_to_svg(diagram, svg_path)
        print(f"SVG written to {svg_path}")
        return

    # Determine output file path.
    if args.output_path is None:
        default_name = "graph.md" if args.output_format == "mermaid" else "graph.dot"
        out_path = Path(default_name)
    else:
        out_path = Path(args.output_path)

    # Wrap Mermaid in a fenced code block so markdown previewers render it.
    content = _wrap_mermaid(diagram) if args.output_format == "mermaid" else diagram

    out_path.write_text(content, encoding="utf-8")
    print(f"Dependency graph written to {out_path}")

    if args.output_format == "mermaid":
        print("Open the file in any Markdown previewer, or paste the contents")
        print("of the ```mermaid block into https://mermaid.live to view online.")
    else:
        print("Render to SVG with:  dot -Tsvg graph.dot -o graph.svg")


if __name__ == "__main__":
    main()
