"""The media table: local image files and the library images they stand for."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol
from urllib.parse import unquote, urlsplit

from wpsync.state import MediaRecord

IMAGES_DIR = "images"


class MissingImage(Exception):
    """The platform lists an image, but its file is gone."""


@dataclass(frozen=True)
class MediaImage:
    id: str
    url: str
    """The copy of the image a post displays."""
    size: str
    """The platform's name for that copy, such as WordPress's `large`."""


class Media(Protocol):
    def remember(self, url: str, media_id: str, size: str) -> str:
        """Record a library image found on pull; return its Markdown source."""
        ...

    def lookup(self, src: str) -> MediaImage | None:
        """The library image a Markdown source refers to, if any."""
        ...


@dataclass(frozen=True)
class Download:
    path: PurePosixPath
    url: str
    media_id: str
    size: str


class MediaLibrary:
    """The media table during a pull: known images and images to download."""

    def __init__(self, root: Path, records: list[MediaRecord]) -> None:
        self.root = root
        self.by_path = {record.path: record for record in records}
        self.by_url = {record.url: record.path for record in records}
        self.pending: dict[PurePosixPath, Download] = {}

    def remember(self, url: str, media_id: str, size: str) -> str:
        path = self.by_url.get(url)
        if path is None:
            path = self._free_path(url, media_id)
            self.by_url[url] = path
            self.pending[path] = Download(path, url, media_id, size)
        return str(path)

    def lookup(self, src: str) -> MediaImage | None:
        path = PurePosixPath(src)
        if path in self.by_path:
            record = self.by_path[path]
            return MediaImage(record.media_id, record.url, record.size)
        if path in self.pending:
            download = self.pending[path]
            return MediaImage(download.media_id, download.url, download.size)
        return None

    def take_pending(self) -> list[Download]:
        downloads = list(self.pending.values())
        self.pending.clear()
        return downloads

    def release(self, download: Download) -> None:
        """Forget a planned download that the converted post does not use."""
        self.by_url.pop(download.url, None)

    def add(self, record: MediaRecord) -> None:
        self.by_path[record.path] = record

    def at_url(self, url: str) -> MediaRecord:
        return self.by_path[self.by_url[url]]

    def _free_path(self, url: str, media_id: str) -> PurePosixPath:
        name = unquote(PurePosixPath(urlsplit(url).path).name) or f"image-{media_id}"
        name = name.replace("/", "-")
        stem, suffix = PurePosixPath(name).stem, PurePosixPath(name).suffix
        candidates = [name, f"{stem}-{media_id}{suffix}"]
        candidates += [f"{stem}-{media_id}-{n}{suffix}" for n in range(2, 1000)]
        for candidate in candidates:
            path = PurePosixPath(IMAGES_DIR) / candidate
            taken = path in self.by_path or path in self.pending
            if not taken and not (self.root / path).exists():
                return path
        raise ValueError(f"no free file name for {url}")
