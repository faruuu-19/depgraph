"""parsers — language-specific import parsers."""

# Directories that are never source files and must be skipped during any
# repo walk.  All three parsers read this constant so the list is maintained
# in a single place.
EXCLUDED_DIRS: frozenset[str] = frozenset(
    {
        # Python virtual environments
        ".venv",
        "venv",
        "env",
        # JavaScript / Node
        "node_modules",
        # Python caches
        "__pycache__",
        ".pytest_cache",
        # Version control
        ".git",
        # Java / Maven build output
        "target",
        # Generic build / distribution artefacts
        "dist",
        "build",
    }
)
