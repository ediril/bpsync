"""Bringing posts from the platform into local files."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Protocol

from wpsync.documents import (
    POSTS_DIR,
    Document,
    LocalDocument,
    body_checksum,
    fields_checksum,
    parse_document,
    serialize_document,
)
from wpsync.markup.markdown import image_sources
from wpsync.media import Download, Media, MediaLibrary, MissingImage
from wpsync.posts import Conversion, FetchedPost, UnrepresentableContent
from wpsync.state import MediaRecord, PostRecord, write_state
from wpsync.storage import write_atomic, write_text_atomic
from wpsync.sync import Action, DiffEntry, SelectionError, match_post


class PullRemote(Protocol):
    def fetch_posts(
        self, ids: list[str] | None = None, slug: str | None = None
    ) -> list[FetchedPost]: ...

    def convert(self, post: FetchedPost, media: Media) -> Conversion: ...

    def download(self, url: str) -> bytes: ...


@dataclass(frozen=True)
class _LocalCandidate:
    """A local file without a post ID, as a match candidate."""

    id: str
    title: str
    slug: str
    document: LocalDocument


@dataclass
class PullResult:
    new: int = 0
    updated: int = 0
    linked: int = 0
    images: int = 0
    missing_images: int = 0
    skipped: int = 0
    changes_kept: int = 0

    def summary(self) -> str:
        pulled = self.new + self.updated + self.linked
        if not pulled and not self.skipped:
            notes = ["Nothing to pull"]
            if self.changes_kept:
                kept = self.changes_kept
                notes.append(f"{kept} post{'s' * (kept != 1)} with local changes")
            if self.missing_images:
                missing = self.missing_images
                notes.append(f"{missing} image{'s' * (missing != 1)} missing")
            return "; ".join(notes) + "."
        parts = [
            f"{count} {label}"
            for count, label in (
                (self.new, "new"),
                (self.updated, "updated"),
                (self.linked, "linked"),
            )
            if count
        ]
        line = f"Pulled {pulled} post{'s' * (pulled != 1)}"
        line += f" ({', '.join(parts)})" if parts else ""
        if self.images:
            line += f", {self.images} image{'s' * (self.images != 1)}"
        if self.missing_images:
            missing = self.missing_images
            line += f"; {missing} image{'s' * (missing != 1)} missing"
        if self.skipped:
            line += f"; {self.skipped} skipped"
        if self.changes_kept:
            line += f"; {self.changes_kept} with local changes left alone"
        return line + "."


class Puller:
    def __init__(
        self,
        root: Path,
        api_root: str,
        remote: PullRemote,
        documents: list[LocalDocument],
        records: dict[str, PostRecord],
        media: list[MediaRecord],
        confirm: Callable[[str], bool],
        report: Callable[[DiffEntry], None],
    ) -> None:
        self.root = root
        self.api_root = api_root
        self.remote = remote
        self.records = records
        self.confirm = confirm
        self.report = report
        self.library = MediaLibrary(root, media)
        self.documents = {
            d.document.post_id: d for d in documents if d.document.post_id
        }
        self.unlinked = [
            _LocalCandidate(str(d.path), d.document.post.title, d.document.post.slug, d)
            for d in documents
            if d.document.post_id is None
        ]
        self.taken = {PurePosixPath(d.path) for d in documents}
        self.result = PullResult()

    def pull(self, ids: list[str] | None = None, slug: str | None = None) -> PullResult:
        fetched = self.remote.fetch_posts(ids=ids, slug=slug)
        if not fetched and (ids or slug):
            named = f"slug '{slug}'" if slug else f"id {ids[0]}"  # type: ignore[index]
            raise SelectionError(f"WordPress has no post with {named}")
        for post in fetched:
            self._pull_post(post)
        if ids is None and slug is None:
            present = {post.id for post in fetched}
            for post_id, record in sorted(
                self.records.items(), key=lambda r: int(r[0])
            ):
                if post_id not in present and post_id in self.documents:
                    self._line(
                        Action.DELETED,
                        post_id,
                        record.path,
                        "deleted on WordPress; local file kept",
                    )
        return self.result

    def _pull_post(self, post: FetchedPost) -> None:
        document = self.documents.get(post.id)
        record = self.records.get(post.id)
        if record is not None and document is None:
            self._line(
                Action.DELETED,
                post.id,
                record.path,
                "deleted locally; not restored",
            )
            return
        if record is not None and document is not None:
            self._pull_tracked(post, document, record)
        elif document is not None:
            self._pull_unrecorded(post, document)
        else:
            self._pull_new(post)

    def _pull_tracked(
        self, post: FetchedPost, document: LocalDocument, record: PostRecord
    ) -> None:
        local = document.document.post
        changed_locally = (
            body_checksum(local) != record.body_checksum
            or fields_checksum(local) != record.fields_checksum
        )
        if post.state.fingerprint == record.remote_fingerprint:
            self.result.changes_kept += changed_locally
            self._refresh(post, document, record, changed_locally)
            return
        path = PurePosixPath(document.path)
        if changed_locally and not self.confirm(
            f"#{post.id} {path} changed locally and on WordPress. "
            "Replace your file with WordPress's version?"
        ):
            self._skip(post.id, path, "changed on both sides; your file is unchanged")
            return
        if self._write(post, path, document.document, Action.CHANGED):
            self.result.updated += 1

    def _refresh(
        self,
        post: FetchedPost,
        document: LocalDocument,
        record: PostRecord,
        changed_locally: bool,
    ) -> None:
        """Bring an unchanged post's address and missing images up to date."""
        missing = tuple(
            url for url in record.missing_images if not self._downloads(url)
        )
        if missing != record.missing_images and not changed_locally:
            path = PurePosixPath(document.path)
            if self._write(post, path, document.document, Action.CHANGED):
                self.result.updated += 1
            return
        self.result.missing_images += len(missing)
        current = replace(record, url=post.url, missing_images=missing)
        if current != record:
            with write_state(self.root, self.api_root) as state:
                state.save(current)

    def _downloads(self, url: str) -> bool:
        try:
            self.remote.download(url)
        except MissingImage:
            return False
        return True

    def _pull_unrecorded(self, post: FetchedPost, document: LocalDocument) -> None:
        path = PurePosixPath(document.path)
        conversion = self._convert(post, path)
        if conversion is None:
            return
        remote = replace(post.post, body=conversion.markdown.strip("\n"))
        if remote == document.document.post:
            for download in self.library.take_pending():
                self.library.release(download)
            self._record(post, path, document.document, [], [])
            self._line(Action.UNCHANGED, post.id, path, "linked; already identical")
            self.result.linked += 1
            return
        if not self.confirm(
            f"{path} has id {post.id} but was never synced here. "
            "Replace it with WordPress's version?"
        ):
            for download in self.library.take_pending():
                self.library.release(download)
            self._skip(post.id, path, "never synced here; your file is unchanged")
            return
        if self._write(post, path, document.document, Action.CHANGED, conversion):
            self.result.linked += 1

    def _pull_new(self, post: FetchedPost) -> None:
        match = match_post(post.post, self.unlinked)
        if match.candidates:
            files = ", ".join(c.id for c in match.candidates)
            self._skip(post.id, None, f"same slug as several local files: {files}")
            return
        if match.post is not None:
            candidate = match.post
            path = PurePosixPath(candidate.id)
            if not self.confirm(
                f"WordPress post #{post.id} {post.post.title!r} has the same slug "
                f"as {path}. Link them and replace the file with WordPress's "
                "version?"
            ):
                self._skip(post.id, path, "same slug as this file; not linked")
                return
            self.unlinked.remove(candidate)
            if self._write(post, path, candidate.document.document, Action.NEW):
                self.result.linked += 1
            return
        path = self._new_path(post)
        self.taken.add(path)
        if self._write(post, path, Document(post.id, post.post), Action.NEW):
            self.result.new += 1

    def _new_path(self, post: FetchedPost) -> PurePosixPath:
        for name in (post.name, f"{post.name}-{post.id}"):
            path = PurePosixPath(POSTS_DIR) / f"{name}.md"
            if path not in self.taken and not (self.root / path).exists():
                return path
        raise ValueError(f"no free file name for post {post.id}")

    def _write(
        self,
        post: FetchedPost,
        path: PurePosixPath,
        existing: Document,
        action: Action,
        conversion: Conversion | None = None,
    ) -> bool:
        if conversion is None:
            conversion = self._convert(post, path)
            if conversion is None:
                return False
        fetched = self._fetch_images(post, path, conversion)
        missing = self.library.take_missing()
        if fetched is None:
            return False
        conversion, files = fetched
        images = []
        for download, data in files:
            write_atomic(self.root / download.path, data, mode=0o644)
            image = MediaRecord(
                download.path,
                hashlib.sha256(data).hexdigest(),
                download.media_id,
                download.url,
                download.size,
            )
            self.library.add(image)
            images.append(image)
        written = Document(
            post.id,
            replace(post.post, body=conversion.markdown.strip("\n")),
            existing.extra,
        )
        write_text_atomic(self.root / path, serialize_document(written), mode=0o644)
        self._record(post, path, written, images, missing)
        self.result.images += len(images)
        self.result.missing_images += len(missing)
        details = []
        if images:
            details.append(f"{len(images)} image{'s' * (len(images) != 1)}")
        if missing:
            details.append(
                f"image{'s' * (len(missing) != 1)} missing: " + ", ".join(missing)
            )
        if conversion.kept:
            details.append("kept as HTML: " + ", ".join(dict.fromkeys(conversion.kept)))
        self._line(action, post.id, path, "; ".join(details))
        return True

    def _fetch_images(
        self, post: FetchedPost, path: PurePosixPath, conversion: Conversion | None
    ) -> tuple[Conversion, list[tuple[Download, bytes]]] | None:
        """Download the images a conversion uses before anything is written.

        An image whose file is gone stays in the post as its original source,
        so the post is converted again without a local copy of it.
        """
        contents: dict[str, bytes] = {}
        while conversion is not None:
            used = image_sources(conversion.markdown)
            downloads = []
            for download in self.library.take_pending():
                if str(download.path) in used:
                    downloads.append(download)
                else:
                    self.library.release(download)
            absent = []
            for download in downloads:
                try:
                    if download.url not in contents:
                        contents[download.url] = self.remote.download(download.url)
                except MissingImage:
                    absent.append(download.url)
            if not absent:
                return conversion, [(d, contents[d.url]) for d in downloads]
            for download in downloads:
                self.library.release(download)
            self.library.missing.extend(absent)
            conversion = self._convert(post, path)
        return None

    def _convert(self, post: FetchedPost, path: PurePosixPath) -> Conversion | None:
        try:
            return self.remote.convert(post, self.library)
        except UnrepresentableContent as error:
            for download in self.library.take_pending():
                self.library.release(download)
            self._skip(post.id, path, f"not pulled: {error}")
            return None

    def _record(
        self,
        post: FetchedPost,
        path: PurePosixPath,
        document: Document,
        images: list[MediaRecord],
        missing: list[str],
    ) -> None:
        # Checksums describe the file as it reads back, exactly as diff will see it.
        written = parse_document(serialize_document(document)).post
        with write_state(self.root, self.api_root) as state:
            for image in images:
                state.save_media(image)
            state.save(
                PostRecord(
                    post.id,
                    path,
                    body_checksum(written),
                    fields_checksum(written),
                    post.state.fingerprint,
                    post.state.format,
                    post.url,
                    tuple(missing),
                )
            )

    def _skip(self, post_id: str, path: PurePosixPath | None, detail: str) -> None:
        self.result.skipped += 1
        self._line(Action.CONFLICT, post_id, path or PurePosixPath("-"), detail)

    def _line(
        self,
        action: Action,
        post_id: str,
        path: PurePosixPath,
        detail: str = "",
    ) -> None:
        self.report(DiffEntry(action, "", post_id, path, detail))
