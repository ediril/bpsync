"""Synchronization state: what each linked post looked like at its last sync."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from wpsync.posts import ContentFormat

STATE_PATH = Path(".wpsync") / "state.db"
SCHEMA_VERSION = 1
SCHEMA = """
CREATE TABLE site (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    api_root TEXT NOT NULL
);
CREATE TABLE posts (
    post_id TEXT PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    body_checksum TEXT NOT NULL,
    fields_checksum TEXT NOT NULL,
    remote_fingerprint TEXT NOT NULL,
    remote_format TEXT NOT NULL CHECK (remote_format IN ('blocks', 'html'))
);
CREATE TABLE media (
    path TEXT PRIMARY KEY,
    checksum TEXT NOT NULL,
    media_id TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    size TEXT NOT NULL
);
"""


class StateError(Exception):
    """Raised when the state database is missing, foreign, or unreadable."""


@dataclass(frozen=True)
class PostRecord:
    post_id: str
    path: PurePosixPath
    """Relative to the profile's local root."""
    body_checksum: str
    fields_checksum: str
    remote_fingerprint: str
    remote_format: ContentFormat


@dataclass(frozen=True)
class MediaRecord:
    path: PurePosixPath
    """Relative to the profile's local root."""
    checksum: str
    """Of the file as downloaded or uploaded."""
    media_id: str
    url: str
    size: str


def _check_site(connection: sqlite3.Connection, path: Path, api_root: str) -> None:
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version != SCHEMA_VERSION:
        raise StateError(f"{path} is not a version {SCHEMA_VERSION} wpsync database")
    row = connection.execute("SELECT api_root FROM site").fetchone()
    if row is None or row[0] != api_root:
        recorded = row[0] if row else "no blog"
        raise StateError(
            f"{path} belongs to {recorded}, not {api_root}; this folder was "
            "synchronized with a different blog"
        )


def _open(root: Path, api_root: str, mode: str) -> sqlite3.Connection:
    path = root / STATE_PATH
    if not path.exists():
        raise StateError(f"{root} is not initialized; run wpsync init")
    connection = sqlite3.connect(f"{path.as_uri()}?mode={mode}", uri=True)
    try:
        _check_site(connection, path, api_root)
    except BaseException:
        connection.close()
        raise
    return connection


@contextmanager
def _read_only(root: Path, api_root: str) -> Iterator[sqlite3.Connection]:
    try:
        connection = _open(root, api_root, "ro")
        try:
            yield connection
        finally:
            connection.close()
    except sqlite3.Error as error:
        raise StateError(f"cannot read {root / STATE_PATH}: {error}") from error


def read_records(root: Path, api_root: str) -> dict[str, PostRecord]:
    """Read every post record without creating or changing the database."""
    with _read_only(root, api_root) as connection:
        rows = connection.execute(
            "SELECT post_id, path, body_checksum, fields_checksum, "
            "remote_fingerprint, remote_format FROM posts"
        ).fetchall()
    return {
        row[0]: PostRecord(
            row[0],
            PurePosixPath(row[1]),
            row[2],
            row[3],
            row[4],
            ContentFormat(row[5]),
        )
        for row in rows
    }


def read_media(root: Path, api_root: str) -> list[MediaRecord]:
    with _read_only(root, api_root) as connection:
        rows = connection.execute(
            "SELECT path, checksum, media_id, url, size FROM media"
        ).fetchall()
    return [MediaRecord(PurePosixPath(row[0]), *row[1:]) for row in rows]


class StateWriter:
    """Writes records inside one transaction per synchronized post."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def save(self, record: PostRecord) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO posts VALUES (?, ?, ?, ?, ?, ?)",
            (
                record.post_id,
                str(record.path),
                record.body_checksum,
                record.fields_checksum,
                record.remote_fingerprint,
                record.remote_format.value,
            ),
        )

    def save_media(self, record: MediaRecord) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO media VALUES (?, ?, ?, ?, ?)",
            (
                str(record.path),
                record.checksum,
                record.media_id,
                record.url,
                record.size,
            ),
        )


def create_state(root: Path, api_root: str) -> None:
    """Create the database that marks the folder as initialized for the blog."""
    path = root / STATE_PATH
    path.parent.mkdir(exist_ok=True)
    try:
        with path.open("x"):
            pass
    except FileExistsError:
        raise StateError(f"{root} is already initialized; run wpsync pull") from None
    try:
        connection = sqlite3.connect(path)
        try:
            with connection:
                connection.executescript(SCHEMA)
                connection.execute("INSERT INTO site VALUES (1, ?)", (api_root,))
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        finally:
            connection.close()
    except sqlite3.Error as error:
        path.unlink()
        raise StateError(f"cannot create {path}: {error}") from error


@contextmanager
def write_state(root: Path, api_root: str) -> Iterator[StateWriter]:
    """Open the database for one transaction."""
    try:
        connection = _open(root, api_root, "rw")
        try:
            with connection:
                yield StateWriter(connection)
        finally:
            connection.close()
    except sqlite3.Error as error:
        raise StateError(f"cannot update {root / STATE_PATH}: {error}") from error
