"""Read a project's git history: materialize a revision, list its commits.

Shared by ``diff --base`` and ``history``.

``git archive`` into a temporary directory rather than ``git worktree``: nothing
is registered in ``.git``, and an interrupted run leaves nothing to prune.
"""

from __future__ import annotations

import io
import subprocess
import tarfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Optional


class GitError(RuntimeError):
    """git refused: not a repository, unknown revision, missing path."""


@dataclass(frozen=True)
class Commit:
    """One commit of the history: full sha, committer date, subject line."""

    sha: str
    date: str
    subject: str

    @property
    def short(self) -> str:
        return self.sha[:7]


@contextmanager
def checkout(project_dir: str, rev: str) -> Iterator[str]:
    """Yield where ``project_dir`` is, as of ``rev``, in a temporary copy.

    Only the project's own subtree is extracted; the copy is removed on exit.
    """
    top, relative = _locate(project_dir)
    commit = _resolve(top, rev)
    paths = [] if relative == "." else [relative]
    archive = _git(top, "archive", "--format=tar", commit, *paths)

    with TemporaryDirectory(prefix="arch-blueprint-") as tmp:
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            # Our own repository's history, but refuse links and absolute paths
            # all the same where this Python can (3.12, and 3.9+ security builds).
            if hasattr(tarfile, "data_filter"):
                tar.extractall(tmp, filter="data")
            else:  # pragma: no cover - old interpreters only
                tar.extractall(tmp)  # noqa: S202
        yield str(Path(tmp) / relative)


def first_parent_commits(
    project_dir: str,
    base: Optional[str],
    head: str,
) -> list[Commit]:
    """Commits on ``head``'s first-parent line that touched the project, oldest first.

    First parents only: on a branch that merges its merge requests, that is one
    commit per merge, dated when it landed. ``base``, when given, is the first
    commit returned whether or not it touched the project — it is the start.
    """
    top, relative = _locate(project_dir)
    head_sha = _resolve(top, head)
    revs = [head_sha]
    start: list[Commit] = []
    if base is not None:
        base_sha = _resolve(top, base)
        revs.append(f"^{base_sha}")
        start = _log(top, [base_sha, "-1"], relative)
    return [*start, *_log(top, ["--first-parent", "--reverse", *revs], relative)]


def tree_id(project_dir: str, sha: str) -> str:
    """The id of ``project_dir``'s tree at ``sha``: equal trees, equal projects."""
    top, relative = _locate(project_dir)
    spec = f"{sha}^{{tree}}" if relative == "." else f"{sha}:{relative}"
    return _git(top, "rev-parse", spec).decode().strip()


def split_patterns(
    patterns: Sequence[str],
    old_root: str,
    new_root: str,
) -> tuple[list[str], list[str]]:
    """Give each side only the patterns whose top-level package it has.

    A merge request that adds (or deletes) a whole package has it on one side
    only; resolving it on the other would fail the run instead of showing the
    package as added. A pattern found on neither side goes to both, so a typo
    still fails the way it does without ``diff``.
    """
    old: list[str] = []
    new: list[str] = []
    for pattern in patterns:
        in_old = _has_package(old_root, pattern)
        in_new = _has_package(new_root, pattern)
        if in_old or not in_new:
            old.append(pattern)
        if in_new or not in_old:
            new.append(pattern)
    return old, new


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


def _has_package(root: str, pattern: str) -> bool:
    return has_source(root, pattern.split(".", 1)[0])


def _locate(project_dir: str) -> tuple[Path, str]:
    """The repository root and ``project_dir`` relative to it, POSIX-style."""
    project = Path(project_dir).resolve()
    top = Path(_git(project, "rev-parse", "--show-toplevel").decode().strip())
    try:
        relative = project.relative_to(top.resolve()).as_posix()
    except ValueError as error:  # e.g. a short vs a long Windows path name
        msg = f"{project_dir} is not inside the repository at {top}"
        raise GitError(msg) from error
    return top, relative


def _resolve(top: Path, rev: str) -> str:
    """The full sha of the commit ``rev`` names."""
    if rev.startswith("-"):  # would be read as an option, not a revision
        msg = f"invalid revision {rev!r}"
        raise GitError(msg)
    return (
        _git(top, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")
        .decode()
        .strip()
    )


def _log(top: Path, args: Sequence[str], relative: str) -> list[Commit]:
    # NUL-separated: a subject can hold any other character.
    output = _git(top, "log", "--format=%H%x00%cs%x00%s", *args, "--", relative)
    commits = []
    for line in output.decode(errors="replace").splitlines():
        sha, date, subject = line.split("\0", 2)
        commits.append(Commit(sha, date, subject))
    return commits


def _git(cwd: Path, *args: str) -> bytes:
    try:
        # git from PATH, as the user runs it; args never start with "-" from input.
        result = subprocess.run(  # noqa: S603
            ["git", *args],  # noqa: S607
            cwd=cwd,
            capture_output=True,
            check=False,
        )
    except OSError as error:
        msg = f"cannot run git: {error}"
        raise GitError(msg) from error
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip()
        if not detail and args[:1] == ("rev-parse",):
            detail = f"unknown revision {args[-1].removesuffix('^{commit}')!r}"
        msg = f"git {args[0]} failed: {detail}"
        raise GitError(msg)
    return result.stdout
