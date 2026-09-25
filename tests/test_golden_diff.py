from __future__ import annotations

import pytest

from tests.conftest import DIFF_CASES, DiffCase, diff_golden_path, run_command


@pytest.mark.parametrize("fmt", ["puml", "d2"])
@pytest.mark.parametrize("case", DIFF_CASES, ids=lambda c: c.name)
def test_diff_output_matches_golden(case: DiffCase, fmt: str) -> None:
    expected = diff_golden_path(fmt, case.name).read_text(encoding="utf-8")
    result = run_command(
        "diff",
        str(case.old),
        str(case.new),
        *case.args,
        "-f",
        fmt,
        check=False,
    )
    assert result.stdout == expected
    assert result.returncode == (0 if case.name == "no_changes" else 1)
