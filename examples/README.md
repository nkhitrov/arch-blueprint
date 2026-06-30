# Examples

A self-contained sample project used to verify multi-root and namespace-package support.

## Layout

```
project_root/                 # passed as <project_dir>; NO __init__.py here (a true project root)
  app1/
    __init__.py
    models.py                 # class User
  app2/
    __init__.py
    service.py                # imports app1.models AND plugins.auth.backend
  plugins/                    # PEP 420 namespace package (NO __init__.py)
    auth/
      __init__.py
      backend.py              # class AuthBackend
```

Three things make this project interesting:

- The **project root has no `__init__.py`**, so `app1`, `app2`, and `plugins` are separate
  top-level packages (the tool appends `project_root` to `sys.path` so they are importable).
- `app2` imports from a **sibling** package (`app1.models`), so a cross-app link should appear.
- `plugins/` is a **PEP 420 namespace package** (no `__init__.py`). grimp cannot graph a namespace
  package directly, so the tool expands it to its regular sub-package `plugins.auth` and graphs
  that. `app2` imports `plugins.auth.backend`, so an `app2 -> plugins` link should appear.

## Run it

From the repo root:

```bash
uv run arch-blueprint examples/project_root -m 'app1.*' -m 'app2.*' -m 'plugins.**'
```

Expected (PlantUML): an `app2 ---> app1` link and an `app2 ---> plugins` link, with no warning and
no crash.

## Namespace package with no source

If a namespace package contains **no** regular sub-package (no `__init__.py` anywhere underneath,
e.g. a directory of compiled-only stubs), there is nothing for grimp to analyze. The tool skips it
and prints a warning to stderr instead of crashing:

```
warning: '<package>' is a namespace package with no analyzable source; skipping.
```

The rest of the diagram is still produced.
