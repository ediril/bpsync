"""Advance the starting version along the first-parent history from its root.

Hatchling evaluates `release_version()` from this file to set the package
version, so every built artifact carries the version computed from Git.
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime
from email.parser import Parser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_PATTERN = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.[1-9][0-9]*")


def git_version(root: Path) -> str:
    """`<major>.<work-day>.<daily-commit>` from the history's root commit.

    The root commit has the starting version. Each later date with commits
    advances the work day by one; the last number counts that day's commits.
    """
    start = json.loads((root / "version.json").read_text())["version"]
    if not isinstance(start, str) or VERSION_PATTERN.fullmatch(start) is None:
        raise ValueError("version.json requires a valid starting version")
    major, work_day, increment = map(int, start.split("."))
    result = subprocess.run(
        ["git", "log", "--first-parent", "--format=%cI", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    dates = [datetime.fromisoformat(line).date() for line in result.stdout.split()]
    if dates != sorted(dates, reverse=True):
        raise ValueError("commit dates go backwards in the first-parent history")
    work_day += len(set(dates)) - 1
    daily_commits = dates.count(dates[0])
    if dates[0] == dates[-1]:
        daily_commits += increment - 1
    return f"{major}.{work_day}.{daily_commits}"


def release_version(root: Path = ROOT) -> str:
    if (root / ".git").exists():
        return git_version(root)
    # A source archive carries the version fixed when it was built.
    metadata = root / "PKG-INFO"
    if not metadata.is_file():
        raise ValueError("version requires a Git checkout or a built source archive")
    version = Parser().parsestr(metadata.read_text())["Version"]
    if version is None or VERSION_PATTERN.fullmatch(version) is None:
        raise ValueError("source archive has an invalid release version")
    return version
