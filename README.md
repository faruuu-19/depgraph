# dep-graph-guard

A language-agnostic **MCP server** that any coding agent (Bob, Claude Code, Cursor, etc.) can call **before touching any source file**. It parses a repository, builds an in-memory dependency graph, and exposes tools for impact analysis — so you always know the full blast radius of a change before you make it.

---

## Table of contents

- [What it does](#what-it-does)
- [Supported languages](#supported-languages)
- [Installation](#installation)
- [Registering with an MCP client](#registering-with-an-mcp-client)
- [MCP tools reference](#mcp-tools-reference)
- [Typical workflow](#typical-workflow)
- [Viewing the dependency graph](#viewing-the-dependency-graph)
  - [Interactive HTML viewer](#interactive-html-viewer)
  - [Mermaid / DOT via CLI](#mermaid--dot-via-cli)
  - [Mermaid / DOT via MCP](#mermaid--dot-via-mcp)
- [Granularity levels](#granularity-levels)
- [Per-repo configuration](#per-repo-configuration)
- [Development](#development)
- [Known limitations](#known-limitations)

---

## What it does

Before every code change, an AI agent should know:

1. **What files will be affected** by editing a particular file or function?
2. **Which tests need to run** to cover those affected files?
3. **Are there any affected files with no test coverage at all?**

dep-graph-guard answers all three by statically parsing imports and call graphs across your entire repository and exposing the results through five MCP tools.

```
your repo  →  dep-graph-guard  →  MCP tools  →  agent makes an informed change
```

---

## Supported languages

| Language | File-level graph | Function-level graph |
|----------|:----------------:|:--------------------:|
| Python | ✅ | ✅ |
| JavaScript / TypeScript | ✅ | ❌ (planned) |
| Java | ✅ | ❌ (planned) |

---

## Installation

### From PyPI

```bash
pip install dep-graph-guard
```

### Development / editable install

```bash
git clone <this-repo>
cd dep-graph-guard
pip install -e ".[dev]"
```

Verify the entry point is on your PATH:

```bash
dep-graph-guard --help
```

**Requirements:** Python ≥ 3.10, `mcp >= 1.0`, `networkx >= 3.0`.

---

## Registering with an MCP client

Add the following block to your client's `mcp.json` (or equivalent config file). The server communicates over **stdio** — no network port needed.

```json
{
  "mcpServers": {
    "dep-graph-guard": {
      "command": "dep-graph-guard",
      "args": [],
      "transport": "stdio"
    }
  }
}
```

Once registered, all five tools below are available to any agent connected to that MCP client.

---

## MCP tools reference

### `build_dependency_graph`

Parse a repo and return a file-level dependency graph for all supported languages.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `repo_path` | string | ✅ | Absolute path to the root of the repository to analyse |

**Returns:** JSON with `nodes`, `edges`, and `stats` (node count, edge count).

---

### `analyze_change_impact`

Returns the full set of files (and optionally functions) that would be affected if the given files change. **Call this before editing anything.**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `repo_path` | string | ✅ | Absolute path to the repository root |
| `changed_files` | string[] | ✅ | Repo-relative paths of files you intend to modify, e.g. `["services/booking.py"]` |
| `changed_functions` | string[] | ❌ | Function node IDs for narrower Python-only analysis, e.g. `["services/booking.py::book_flight"]` |

**Returns:** JSON with:
- `changed_files` — the files you passed in
- `directly_affected` — files that directly import any changed file
- `transitively_affected` — all files that would break (full downstream set)
- `total_affected_count`
- `function_impact` *(only when `changed_functions` is provided)* — same breakdown at function granularity

---

### `get_required_tests`

Cross-references the `affected_nodes` list (from `analyze_change_impact`) against the test suite and flags any nodes that have no coverage. **Call this right after `analyze_change_impact`.**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `repo_path` | string | ✅ | Absolute path to the repository root |
| `affected_nodes` | string[] | ✅ | List of node IDs returned by `analyze_change_impact` |

**Returns:** JSON with:
- `tests_to_run` — test files that cover at least one affected node
- `uncovered_nodes` — affected nodes with no matching test file (write tests here!)

---

### `build_dependency_graph_detailed`

Like `build_dependency_graph` but adds **function-level nodes** for Python files — individual functions and methods become first-class nodes, linked by `contains` and `calls` edges.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `repo_path` | string | ✅ | Absolute path to the repository root |
| `granularity` | string | ❌ | Currently only `"function"` is supported (default) |

**Returns:** Same `nodes`/`edges`/`stats` JSON as `build_dependency_graph`, with additional counts for file nodes, function nodes, and edge counts broken down by kind (`import`, `contains`, `calls`).

---

### `visualize_dependency_graph`

Returns a text-based diagram of the dependency graph. Paste Mermaid output into any Markdown previewer or [mermaid.live](https://mermaid.live). Pipe DOT output to Graphviz.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `repo_path` | string | ✅ | Absolute path to the repository root |
| `output_format` | string | ❌ | `"mermaid"` (default) or `"dot"` |

**Returns:** A plain string containing the diagram.

---

## Typical workflow

This is the pattern every agent should follow before making any code change:

```
1.  analyze_change_impact(repo_path, changed_files=["path/to/file.py"])
        ↓ returns affected_nodes

2.  get_required_tests(repo_path, affected_nodes=[...])
        ↓ returns tests_to_run + uncovered_nodes

3.  Read the test files listed in tests_to_run to understand test conventions.

4.  Write or update tests for every node in uncovered_nodes.

5.  Make the actual code change.
```

### Example — file-level analysis

```python
# Step 1 — what breaks if I change models.py?
analyze_change_impact(
    repo_path="/home/user/myproject",
    changed_files=["models.py"]
)
# → directly_affected:    ["services/user_service.py", "services/flight_service.py"]
# → transitively_affected: ["services/user_service.py", "services/flight_service.py", "api/routes.py"]

# Step 2 — which tests cover those files?
get_required_tests(
    repo_path="/home/user/myproject",
    affected_nodes=["services/user_service.py", "services/flight_service.py", "api/routes.py"]
)
# → tests_to_run:    ["tests/test_user_service.py", "tests/test_routes.py"]
# → uncovered_nodes: ["services/flight_service.py"]  ← write a test here first!
```

### Example — function-level analysis (Python)

```python
# Narrow the blast radius to a single function
analyze_change_impact(
    repo_path="/home/user/myproject",
    changed_files=["models.py"],
    changed_functions=["models.py::get_user"]
)
# → function_impact.transitively_affected: ["services/user_service.py::process_user"]
#   (services/flight_service.py is NOT listed — it never calls get_user)
```

---

## Viewing the dependency graph

### Interactive HTML viewer

`scripts/dep_graph_viewer.html` is a **zero-dependency interactive graph explorer**. Open it directly in any browser — no server or build step required.

```bash
# macOS
open scripts/dep_graph_viewer.html

# Windows
start scripts/dep_graph_viewer.html

# Linux
xdg-open scripts/dep_graph_viewer.html
```

#### Navigation

| Action | How |
|--------|-----|
| **Zoom** | Scroll wheel, centred on cursor |
| **Pan** | Drag the background |
| **Move a node** | Drag it — it stays pinned where you drop it |
| **Highlight neighbours** | Click any node — everything else fades; only direct 1-hop connections stay lit. Click again to clear |
| **Filter edge types** | Toggle the checkboxes in the toolbar — graph re-simulates instantly |
| **Show test nodes** | Enable the "show tests" checkbox to add the test-file cluster |
| **Search** | Type in the search box — non-matching nodes fade to 10% opacity |

#### Colour coding

**Node colours** indicate the kind of symbol:

| Colour | Kind |
|--------|------|
| 🔵 Blue ring | Source file |
| 🔴 Red ring | ORM / model class |
| 🟡 Yellow ring | Schema class |
| 🟢 Green ring | Function or method |

**Edge colours** indicate the relationship:

| Colour | Edge kind | Meaning |
|--------|-----------|---------|
| Yellow solid | `import` | File imports another file |
| Blue solid | `contains` | File owns a function node |
| Purple dashed | `calls` | Function calls another function |

---

### Mermaid / DOT via CLI

`scripts/visualize.py` generates a text-based snapshot you can render anywhere.

```bash
# Mermaid → graph.md  (paste into any Markdown previewer or mermaid.live)
python scripts/visualize.py /path/to/repo

# Explicit output path
python scripts/visualize.py /path/to/repo -o deps.md

# DOT format → deps.dot
python scripts/visualize.py /path/to/repo -f dot -o deps.dot

# DOT → SVG in one step (requires Graphviz 'dot' on PATH)
python scripts/visualize.py /path/to/repo -f dot --svg deps.svg
```

To render a `.dot` file manually with Graphviz:

```bash
dot -Tsvg graph.dot -o graph.svg
dot -Tpng graph.dot -o graph.png
```

---

### Mermaid / DOT via MCP

Ask the agent directly:

```
visualize_dependency_graph(repo_path="/path/to/repo", output_format="mermaid")
```

Paste the returned string into [mermaid.live](https://mermaid.live) or any Markdown previewer that supports Mermaid fences.

---

## Granularity levels

dep-graph-guard supports two analysis levels:

### File-level (default — all languages)

Every source file is a single node. Edges represent `import` relationships between files. This is the recommended starting point and works for Python, JavaScript/TypeScript, and Java.

### Function-level (Python only)

`build_dependency_graph_detailed` and the `changed_functions` parameter of `analyze_change_impact` extend the graph with individual function and method nodes.

**Function node ID format:**
- Top-level function: `"relative/path/file.py::function_name"`
- Method: `"relative/path/file.py::ClassName.method_name"`

**Additional edge kinds:**

| Edge kind | Meaning |
|-----------|---------|
| `import` | File → file it imports (same as file-level) |
| `contains` | File → function it defines |
| `calls` | Function → function it calls |

**Why function-level matters:**

```
# File-level blast radius for models.py:
service_a.py, service_b.py   ← both caught (models.py is imported by both)

# Function-level blast radius for models.py::get_user:
service_a.py::process_user   ← only the caller of get_user
                               service_b.py is NOT included — it never calls get_user
```

This precision matters when `models.py` is large and only one function inside it changed.

---

## Per-repo configuration

Create a `dep-graph-guard.json` in the root of the repository being analysed to override test-detection conventions:

```json
{
  "test_patterns": ["test_*.py", "*.test.ts", "*Test.java"],
  "test_dirs": ["tests/", "__tests__/", "src/test/"]
}
```

This is useful when your project places tests in non-standard directories or uses a non-standard naming convention.

---

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run the full test suite
pytest tests/

# Run only the parser tests
pytest tests/test_python_parser.py tests/test_js_ts_parser.py tests/test_java_parser.py

# Run end-to-end tests
pytest tests/e2e/
```

Project layout:

```
dep-graph-guard/
├── src/dep_graph_guard/
│   ├── server.py          # MCP server + all tool handlers
│   ├── graph.py           # DependencyGraph (networkx wrapper)
│   ├── test_mapper.py     # Maps affected nodes → test files
│   └── parsers/
│       ├── python_parser.py
│       ├── js_ts_parser.py
│       └── java_parser.py
├── scripts/
│   ├── dep_graph_viewer.html   # Interactive browser-based graph viewer
│   └── visualize.py            # CLI for Mermaid/DOT export
├── tests/
│   ├── fixtures/               # Sample repos (Python, JS/TS, Java)
│   └── e2e/                    # End-to-end integration tests
└── pyproject.toml
```

---

## Known limitations

### JavaScript / TypeScript

- **Bare module specifiers are skipped.** `import axios from 'axios'` references an npm package, not a local file — it is intentionally omitted.
- **Dynamic path expressions are not resolved.** Template-literal or variable-based imports (e.g. `` import(`./plugins/${name}`) ``) are silently skipped.
- **`node_modules/` is not explicitly excluded.** Bare specifiers are dropped before any file-system lookup so `node_modules` content is never added in practice, but the directory is not blocklisted. Add it to `dep-graph-guard.json` if your repo is large.
- **No test files = all nodes uncovered.** If a sub-project has no files matching the test detection patterns, every affected node appears in `uncovered_nodes`. This is correct and intentional.

### Python

- **Relative imports above the repo root are silently dropped.**
- **`__init__.py` packages are treated as regular nodes.** An import of `services` may emit edges to both `services/__init__.py` and `services/booking.py` depending on the import style.
- **Function-level call resolution is best-effort.** Dynamic dispatch, `getattr`-based calls, and `module.function()` attribute access are not tracked. `from module import name` and same-file calls are resolved.

### Java

- **Only `import` statements are parsed.** `extends` / `implements` relationships are not captured.
- **Wildcard imports (`import com.example.*`) are dropped.** Specific class resolution requires a full type-resolution pass.
- **Non-standard test directories require a `dep-graph-guard.json` override.** By default only `*Test.java` files under `src/test/` are treated as tests.
