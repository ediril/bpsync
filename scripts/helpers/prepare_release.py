#!/usr/bin/env python3
"""Build and validate release artifacts without publishing them."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from check_release import ROOT, validate_release


def run(*arguments: str) -> None:
    print(f"\n> {shlex.join(arguments)}", flush=True)
    subprocess.run(arguments, cwd=ROOT, check=True)


def installed_command(venv: Path) -> Path:
    directory = "Scripts" if os.name == "nt" else "bin"
    suffix = ".exe" if os.name == "nt" else ""
    return venv / directory / f"wpsync{suffix}"


def main() -> None:
    uv = shutil.which("uv")
    if uv is None:
        raise SystemExit("release preparation stopped: uv is required")
    version = validate_release()
    destination = ROOT / "dist" / "wpsync" / version
    if destination.exists():
        raise SystemExit(
            f"release preparation stopped: {destination.relative_to(ROOT)} "
            "already exists"
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{version}-", dir=destination.parent))
    try:
        run(sys.executable, "-m", "ruff", "check", ".")
        run(sys.executable, "-m", "pytest")
        run(uv, "build", "--out-dir", os.fspath(staging))

        wheels = tuple(staging.glob("*.whl"))
        source_archives = tuple(staging.glob("*.tar.gz"))
        if len(wheels) != 1 or len(source_archives) != 1:
            raise SystemExit(
                "release preparation stopped: expected exactly one wheel and "
                "one source archive"
            )
        artifacts = (*wheels, *source_archives)
        run(sys.executable, "-m", "twine", "check", *(map(os.fspath, artifacts)))

        with tempfile.TemporaryDirectory(prefix="wpsync-install-check-") as temp:
            venv = Path(temp) / "venv"
            run(uv, "venv", "--quiet", os.fspath(venv))
            run(
                uv,
                "pip",
                "install",
                "--quiet",
                "--python",
                os.fspath(venv),
                os.fspath(wheels[0]),
            )
            output = subprocess.check_output(
                [os.fspath(installed_command(venv)), "--version"],
                cwd=ROOT,
                text=True,
            ).strip()
            if output != version:
                raise SystemExit(
                    "release preparation stopped: installed CLI reported "
                    f"{output!r}, expected {version!r}"
                )
            print(f"Installed CLI version valid: {output}")

        staging.rename(destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)

    relative_destination = destination.relative_to(ROOT)
    print(f"\nRelease {version} is ready in {relative_destination}/")


if __name__ == "__main__":
    main()
