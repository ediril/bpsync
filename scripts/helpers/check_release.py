#!/usr/bin/env python3
"""Validate release identity before building or publishing distributions."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYPROJECT_FILE = ROOT / "pyproject.toml"

sys.path.insert(0, str(ROOT / "build_backend"))
from versioning import release_version as source_version  # noqa: E402

CONSOLE_SCRIPTS_PATTERN = re.compile(
    r"^\[project\.scripts\]\s*$\n(?P<body>.*?)(?=^\[|\Z)",
    re.MULTILINE | re.DOTALL,
)


def release_version() -> str:
    return source_version(ROOT)


def validate_release(tag: str | None = None) -> str:
    version = release_version()
    if tag is not None and tag != f"v{version}":
        raise SystemExit(f"release check failed: tag {tag!r} does not match v{version}")

    scripts_match = CONSOLE_SCRIPTS_PATTERN.search(PYPROJECT_FILE.read_text())
    if scripts_match is None or scripts_match["body"].strip() != (
        'bpsync = "bpsync.cli:main"'
    ):
        raise SystemExit(
            "release check failed: pyproject.toml must expose only the "
            "bpsync = bpsync.cli:main console script"
        )

    # The version describes the last commit, so artifacts must contain exactly it.
    changes = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    if changes.strip():
        raise SystemExit(
            "release check failed: commit or stash local changes first; "
            f"version {version} describes the last commit\n{changes}"
        )

    print(f"Release identity valid: {version}")
    return version


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--tag",
        help="release tag to verify; must be v followed by the package version",
    )
    arguments = parser.parse_args()
    validate_release(arguments.tag)


if __name__ == "__main__":
    main()
