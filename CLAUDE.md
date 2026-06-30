# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

arch-blueprint is a Python tool that generates architecture diagrams (PlantUML, D2) for Python projects by analyzing module dependencies and class hierarchies. It has two main modes:

1. **Module mode**: Analyzes import graphs between Python modules (default CLI behavior)
2. **Object mode**: Analyzes class hierarchies and dependencies (experimental, via run.py)

## Development Commands

This project uses `uv` for dependency management and task running.

### Setup
```bash
uv sync  # Install dependencies
```

### Running the Tool
```bash
# Module analysis (main CLI)
uv run arch_blueprint <project_dir> -m <module_patterns> [-f puml|d2]

# Object analysis (experimental, via run.py)
uv run python run.py
```

### Linting and Type Checking
```bash
# Format code
uv run ruff format src

# Run linter with auto-fix
uv run ruff check --fix src

# Type checking
uv run mypy src
```

### Pre-commit Hooks
```bash
pre-commit install
pre-commit run --all-files
```

## Architecture

### Two Analysis Modes

**Module Mode** (src/arch_blueprint/modules/):
- Uses `grimp` library to build import graphs between Python modules
- Entry point: `ArchBlueprint` class in `blueprint.py`
- Core components:
  - `BlueprintModule`: Represents a module with its dependencies
  - `CycleAnalyzer`: Detects cyclic dependencies between namespaces
  - Renderers: `PlantUmlModuleRenderer`, `D2ModuleRenderer` (in `modules/renderers/`)
- Models: `ModuleEdge`, `NamespaceLink`, `CyclicDependency` (in `modules/models.py`)

**Object Mode** (src/arch_blueprint/objects/):
- Uses `libcst` to parse Python AST and analyze class hierarchies
- Entry point: `BlueprintObjectParser` class in `parsers.py`
- Core components:
  - `BlueprintClassCollector`, `ClassInfoCollector`: AST visitors for extracting class info
  - `PlantUmlUseCaseRenderer`: Renders use case diagrams from class relationships
- Models: `BlueprintObject`, `BlueprintPackage` (in `objects/models.py`)

### Key Concepts

**Module Mode Flow**:
1. Build import graph using `grimp.build_graph()`
2. Filter modules based on patterns (supports glob-like syntax: `*`, `**`)
3. Analyze dependencies and detect namespace-level cycles
4. Render to PlantUML or D2 format

**Object Mode Flow**:
1. Scan directory tree for Python files (respects .gitignore)
2. Parse each file with `libcst` to extract class definitions
3. Filter classes by parent class hierarchy (e.g., find all UseCase subclasses)
4. Build dependency graph based on class references
5. Render as PlantUML use case diagram

**Namespace Extraction**: Both modes extract "namespaces" from module paths by splitting on dots and finding common prefixes to group related modules.

**Cycle Detection**: Module mode detects bidirectional dependencies between namespaces, with optional detailed module-level edges.

## Code Style

- Python 3.11+ required
- Strict type checking with mypy (see pyproject.toml for config)
- Extensive ruff rules enabled (see pyproject.toml lint.select)
- Key ignored rules: D105, D107, D212 (docstring rules), D100, D104 (module/package docstrings)
- PEP 257 docstring convention
- Use pathlib for file operations
- Use dataclasses for models (frozen=True for immutability where appropriate)

## Important Notes

- Main CLI uses module mode; object mode is experimental (only accessible via run.py)
- The `grimp` library is used for import graph analysis; it caches results in `.grimp_cache/`
- Module patterns support wildcards: `myapp.module.*` (one level), `myapp.module.**` (recursive)
- Object mode can filter by parent classes to find specific patterns (UseCase, EventHandler, etc.)
- Highlighting feature exists in both renderers for emphasizing specific packages/modules
