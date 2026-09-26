"""What a project directory holds, read from the files alone.

No import machinery and no grimp: these answer "is there code to analyze here"
before anything is resolved — for a git checkout of an old commit, and for a
user who gave no ``-m`` and wants every package drawn.
"""

from __future__ import annotations

from pathlib import Path


def has_source(root: str, name: str) -> bool:
    """Whether the dotted module ``name`` exists under ``root`` with code to analyze.

    A directory alone is not enough: a project's first commits often have the
    package directory before any Python in it. The test on the top-level
    package mirrors what ``GrimpSource`` can build — a module file, a regular
    package, or a namespace package with a regular package somewhere below.
    """
    base = Path(root)
    parts = name.split(".")
    path = base.joinpath(*parts)
    if not (path.is_dir() or path.with_name(f"{path.name}.py").is_file()):
        return False
    top = base / parts[0]
    return top.with_name(f"{top.name}.py").is_file() or _has_package_below(top)


def detect_roots(project_dir: str) -> list[str]:
    """The top-level packages under ``project_dir``, sorted.

    A package is a directory ``GrimpSource`` can build: a regular package, or a
    namespace package with a regular one somewhere below. A lone module file is
    left out — ``module.**`` would select nothing, and a project is its
    packages. Hidden directories are skipped (``.venv``, ``.git``).
    """
    try:
        children = sorted(Path(project_dir).iterdir())
    except OSError:
        return []
    return [
        child.name
        for child in children
        if child.is_dir()
        and child.name.isidentifier()
        and not child.name.startswith(".")
        and _has_package_below(child)
    ]


def is_package(directory: str) -> bool:
    """Whether ``directory`` is itself a regular package (has ``__init__.py``)."""
    return (Path(directory) / "__init__.py").is_file()


def _has_package_below(directory: Path) -> bool:
    if (directory / "__init__.py").is_file():
        return True
    try:
        children = list(directory.iterdir())
    except OSError:
        return False
    return any(
        child.is_dir() and child.name.isidentifier() and _has_package_below(child)
        for child in children
    )
