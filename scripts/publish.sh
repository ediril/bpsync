#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    echo "Usage: scripts/publish.sh [--prepare]"
    echo "Build and validate the current release if needed, then publish it to PyPI."
    echo "Uses dist/wpsync/<version>/ if already prepared. Set PYTHON to select an interpreter."
    echo "Use --prepare to build and validate artifacts without publishing."
    exit 0
fi
prepare_only=false
if [[ $# -eq 1 && "$1" == "--prepare" ]]; then
    prepare_only=true
elif [[ $# -ne 0 ]]; then
    echo "Usage: scripts/publish.sh [--prepare]" >&2
    exit 2
fi

release_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$release_root"

release_python="${PYTHON:-}"
if [[ -z "$release_python" ]]; then
    if [[ -x "$release_root/.venv/bin/python" ]]; then
        release_python="$release_root/.venv/bin/python"
    else
        release_python=python3
    fi
fi

"$release_python" scripts/helpers/check_release.py
release_version="$("$release_python" -c \
    'import sys; sys.path.insert(0, "scripts/helpers"); from check_release import release_version; print(release_version())')"
release_directory="dist/wpsync/$release_version"

if [[ ! -d "$release_directory" ]]; then
    "$release_python" scripts/helpers/prepare_release.py
else
    echo "Using prepared release: $release_directory/"
fi

release_wheel="$release_directory/wpsync-$release_version-py3-none-any.whl"
release_source="$release_directory/wpsync-$release_version.tar.gz"
if [[ ! -f "$release_wheel" || ! -f "$release_source" ]]; then
    echo "Release is incomplete: expected both wheel and source archive in $release_directory/" >&2
    exit 1
fi

"$release_python" -m twine check "$release_wheel" "$release_source"
if [[ "$prepare_only" == true ]]; then
    echo "Release $release_version is ready in $release_directory/"
    exit 0
fi
echo "Publishing wpsync $release_version to PyPI..."
"$release_python" -m twine upload --repository pypi \
    "$release_wheel" "$release_source"
echo "Published: https://pypi.org/project/wpsync/$release_version/"
