import importlib.util
import os
import subprocess
from pathlib import Path

import pytest

BACKEND = Path(__file__).parents[1] / "build_backend" / "versioning.py"
spec = importlib.util.spec_from_file_location("versioning", BACKEND)
versioning = importlib.util.module_from_spec(spec)
spec.loader.exec_module(versioning)


def commit(root, date):
    environment = {
        **os.environ,
        "GIT_AUTHOR_DATE": date,
        "GIT_COMMITTER_DATE": date,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }
    subprocess.run(
        ["git", "commit", "--allow-empty", "-qm", date],
        cwd=root,
        env=environment,
        check=True,
    )
    return versioning.release_version(root)


def test_versions_advance_by_work_day_and_count_each_days_commits(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "version.json").write_text('{"version": "0.1.1"}')

    versions = [
        commit(tmp_path, "2026-10-25T09:00:00+00:00"),
        commit(tmp_path, "2026-10-25T17:00:00+00:00"),
        commit(tmp_path, "2026-10-28T09:00:00+00:00"),
        commit(tmp_path, "2026-10-28T10:00:00+00:00"),
        commit(tmp_path, "2026-10-29T08:00:00+00:00"),
    ]

    assert versions == ["0.1.1", "0.1.2", "0.2.1", "0.2.2", "0.3.1"]


def test_a_source_archive_keeps_its_built_version_without_git(tmp_path):
    (tmp_path / "PKG-INFO").write_text(
        "Metadata-Version: 2.4\nName: bpsync\nVersion: 0.4.2\n"
    )

    assert versioning.release_version(tmp_path) == "0.4.2"

    (tmp_path / "PKG-INFO").unlink()
    with pytest.raises(ValueError, match="Git checkout or a built source archive"):
        versioning.release_version(tmp_path)
