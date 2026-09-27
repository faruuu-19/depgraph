# dep-graph-guard

A language-agnostic MCP server that any coding agent (Bob, Claude Code, etc.) can call **before making a code change** to any repository. It parses source files, builds an in-memory dependency graph, and exposes three MCP tools for impact analysis.

## Tools

| Tool | Description |
|------|-------------|
| `build_dependency_graph` | Parse a repo and return a file-level dependency graph (all languages). |
| `analyze_change_impact` | Return the full downstream-dependent set for changed files. Accepts an optional `changed_functions` parameter for narrower function-level blast radius (Python only). |
| `get_required_tests` | Cross-reference affected nodes with the test suite; flag uncovered nodes. |
| `build_dependency_graph_detailed` | Like `build_dependency_graph` but adds function nodes, `contains` edges, and `calls` edges for Python files. |
| `visualize_dependency_graph` | Return a Mermaid or Graphviz DOT diagram of the dependency graph. |

**Supported languages:** Python, JavaScript / TypeScript, Java.

### Granularity levels

dep-graph-guard supports two levels of analysis granularity:

**File-level (default, all languages)**
All tools operate at file granularity by default.  `build_dependency_graph`,
`analyze_change_impact`, and `get_required_tests` treat each source file as a
single node.  This is the recommended starting point and works for Python,
JavaScript/TypeScript, and Java.

**Function-level (Python only)**
`build_dependency_graph_detailed` and the `changed_functions` parameter of
`analyze_change_impact` extend analysis to individual function and method
definitions within Python files.

Function nodes use the ID format `"file.py::function_name"` for top-level
functions and `"file.py::ClassName.method_name"` for methods.

Three new edge kinds are introduced:

| Edge kind | Meaning |
|-----------|---------|
| `contains` | File → function it defines |
| `calls` | Function → function it calls (same-file or cross-file via imports) |
| `import` | File → file it imports (unchanged from file-level) |

Function-level analysis is currently **Python-only**.  JavaScript/TypeScript and
Java files remain at file granularity even when `build_dependency_graph_detailed`
is used.  Function-level support for those languages is planned for a future
release.

## Installation

### From PyPI (once published)

```bash
pip install dep-graph-guard
```

### Editable / development install

```bash
git clone <this-repo>
cd dep-graph-guard
pip install -e ".[dev]"
```

Verify the entry point is available:

```bash
dep-graph-guard --help
```

## Registering with an MCP client

Add the following to your client's `mcp.json` (or equivalent configuration file):

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

## Optional per-repo configuration

Create a `dep-graph-guard.json` in the root of the repository being analysed to override test-detection conventions:

```json
{
  "test_patterns": ["test_*.py", "*.test.ts"],
  "test_dirs": ["tests/", "__tests__/"]
}
```

## Development

```bash
pip install -e ".[dev]"
pytest tests/
```

## Visual graph viewer

`scripts/dep_graph_viewer.html` is a zero-dependency interactive graph explorer.
Open it directly in any browser — no server or build step required.

```bash
open scripts/dep_graph_viewer.html          # macOS
start scripts/dep_graph_viewer.html         # Windows
xdg-open scripts/dep_graph_viewer.html      # Linux
```

### Navigation

| Action | How |
|--------|-----|
| **Zoom** | Scroll wheel, centred on cursor |
| **Pan** | Drag the background |
| **Move a node** | Drag it — it stays pinned where you drop it |
| **Highlight neighbours** | Click any node — everything else fades; only direct 1-hop connections stay lit. Click again to clear |
| **Filter edge types** | Toggle the three checkboxes in the toolbar — graph re-simulates instantly |
| **Show test nodes** | Enable the "show tests" checkbox to add the test-file cluster |
| **Search** | Type in the search box — non-matching nodes fade to 10% opacity |

### Colour coding

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

### Generating the Mermaid / DOT equivalent

For a quick text-based snapshot, use `scripts/visualize.py`:

```bash
# Mermaid → graph.md  (paste into any Markdown previewer)
python scripts/visualize.py /path/to/repo

# DOT → SVG (requires Graphviz)
python scripts/visualize.py /path/to/repo --svg graph.svg
```

## Granularity comparison example

Given a Python backend where `models.py` defines `get_user()` and `get_flight()`,
and two service files each import exactly one of them:

```
# File-level blast radius for models.py:
service_a.py, service_b.py   ← both caught (models.py is imported by both)

# Function-level blast radius for models.py::get_user:
service_a.py::process_user   ← only the caller of get_user is caught
                               service_b is not affected
```

This precision matters when `models.py` is large and you only changed one
function inside it.

## Known Limitations

The following limitations were identified during end-to-end testing against the
[Galaxium Travels](https://github.com/example/galaxium-travels) multi-language
mono-repo.

### JavaScript / TypeScript parser

- **Bare module specifiers are skipped intentionally.**
  Imports such as `import axios from 'axios'` or `import React from 'react'`
  reference npm packages, not local files.  The parser correctly omits them
  because there is no corresponding source file inside the repo root.  If a
  project re-exports a bare specifier through a local barrel file the barrel
  itself will still be tracked; only the npm package import is dropped.

- **Dynamic path expressions are not resolved.**
  Template-literal or variable-based imports (e.g.
  `import(\`./plugins/${name}\`)`) cannot be statically evaluated and are
  silently skipped.

- **`node_modules/` and build output directories are not explicitly excluded.**
  The parser resolves candidate files relative to the repo root.  Because bare
  specifiers are dropped before any file-system lookup, `node_modules` content
  is never added to the graph in practice, but the directory is not
  explicitly blocklisted.  Consider adding `node_modules` to a
  `dep-graph-guard.json` exclusion list if your repo is large.

- **No test files in frontend projects.**
  If a sub-project contains no test files that match the detection conventions
  (`*.test.ts`, `*.spec.ts`, `__tests__/**`), every affected node will appear
  in `uncovered_nodes` and `tests_to_run` will be empty.  This is intentional
  and correct behaviour — the tool accurately reports the absence of test
  coverage.

### Python parser

- **Relative imports from outside the repo root are silently dropped.**
  A `from .. import foo` that would resolve to a path above the repo root is
  ignored rather than raising an error.

- **`__init__.py` namespace packages are treated as regular nodes.**
  An import of `services` may resolve to either `services/__init__.py` or
  `services/booking.py` depending on the import style used; both edges are
  emitted when both files exist.

- **Function-level analysis is Python-only.**
  `build_dependency_graph_detailed` and `analyze_change_impact(changed_functions=…)`
  only add function nodes for `.py` files.  JavaScript/TypeScript and Java files
  are represented as file nodes even in the detailed graph.

- **Function-level call resolution is best-effort.**
  The call graph is extracted via static AST analysis of `ast.Call` nodes.
  Dynamic dispatch (virtual method calls, `getattr`-based calls, decorators
  that replace callables) cannot be resolved and are silently omitted.
  Same-file calls and cross-file calls for names explicitly imported with
  `from module import name` are resolved; calls through module-attribute
  access (`module.function()`) are not yet tracked.

### Java parser

- **Only `import` statements are parsed; `extends`/`implements` references are
  not.**  Class inheritance and interface implementation create implicit
  dependencies that are not currently captured.

- **Wildcard imports (`import com.example.*`) are dropped.**
  The parser cannot resolve which specific classes a wildcard import covers
  without a full type-resolution pass, so wildcard edges are omitted to avoid
  false positives.

- **Only files under `src/main/` are treated as source; `src/test/` files
  whose naming convention matches `*Test.java` are treated as test files.**
  Projects that place tests in non-standard directories will need a
  `dep-graph-guard.json` override.
