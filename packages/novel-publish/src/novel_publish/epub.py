"""EPUB volumes: the selected chapters of each range of `size` chapter numbers as one book.

The output folder is owned by `build_epub`: it holds exactly one file per
volume the current selections call for. A volume is rebuilt when one of its
chapters is stale (new, changed, re-selected or pruned, as
`NovelStore.plan_build` reports) or when its file is missing. The fingerprint
covers the novel's metadata and cover as well as this builder, so a new author
or cover rebuilds every volume. Volumes are written one at a time and recorded
as soon as each is done, so an interrupted build resumes where it stopped.
"""

import hashlib
import os
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from ebooklib import epub
from markupsafe import Markup
from novel_core import KeyRange, NovelMeta, NovelStore, OutputKind, Selected, chapter_heading

from novel_publish import render
from novel_publish.site import anchor

VOLUME_SIZE = 100

type Progress = Callable[[KeyRange, int, int], None]  # (volume range, index from 1, total)

_CSS = """\
body { margin: 0 4%; line-height: 1.5; }
h2.chapter { text-align: center; margin: 1.5em 0 1em; }
p { margin: 0 0 0.8em; }
hr.separator { border: 0; border-top: 1px solid #888; width: 30%; margin: 1.5em auto; }
p.system { font-family: monospace; border-left: 3px solid #888; padding-left: 0.6em; }
aside.note { font-size: 0.9em; font-style: italic; }
"""


@dataclass(frozen=True)
class EpubReport:
    volumes: int  # files the novel has after the build
    built: tuple[KeyRange, ...]
    deleted: tuple[str, ...]  # file names of volumes no longer called for


def build_epub(
    store: NovelStore,
    out_dir: Path,
    slug: str,
    *,
    size: int = VOLUME_SIZE,
    cover: bytes | None = None,
    force: bool = False,
    progress: Progress | None = None,
) -> EpubReport:
    """Build the novel's stale volumes into out_dir as `<slug>_0001-0100.epub`, ...; `force` rebuilds all.

    The slug names the files (Calibre would misread a "Title - Author" file name)
    and makes up each volume's identifier, so a rebuilt volume replaces the old
    one in a reader's library.
    """
    meta = store.meta
    fp = fingerprint(meta, cover, size)
    plan = store.plan_build(OutputKind.EPUB, fp)
    volumes = _volumes(store.selection(), size)
    names = {r: f"{slug}_{r.start:04d}-{r.end:04d}.epub" for r in volumes}

    stale = {KeyRange.containing(s.key.number, size) for s in plan.to_build}
    stale |= {KeyRange.containing(r.built_key.number, size) for r in plan.to_prune}
    todo = [r for r in volumes if force or r in stale or not (out_dir / names[r]).exists()]

    for i, r in enumerate(todo, start=1):
        if progress:
            progress(r, i, len(todo))
        chapters = volumes[r]
        book = _book(store, meta, chapters, cover, _identifier(slug, r), series_index=r.start // size + 1)
        _write(out_dir / names[r], book)
        for s in chapters:
            store.record_output(OutputKind.EPUB, s, fp, names[r])
    for row in plan.to_prune:
        store.prune_output(OutputKind.EPUB, row.built_key)

    wanted = set(names.values())
    deleted = sorted(f.name for f in out_dir.glob("*.epub") if f.name not in wanted) if out_dir.exists() else []
    for name in deleted:
        (out_dir / name).unlink()
    return EpubReport(len(volumes), tuple(todo), tuple(deleted))


def fingerprint(meta: NovelMeta, cover: bytes | None, size: int) -> str:
    """Changes with the novel's metadata, its cover, the volume size or this builder."""
    h = hashlib.sha256()
    h.update(repr((meta.title, meta.author, meta.language, meta.tags, size)).encode())
    h.update(hashlib.sha256(cover).digest() if cover else b"no cover")
    for module in (__file__, render.__file__):
        h.update(Path(module).read_bytes())
    return h.hexdigest()


def _volumes(selection: Iterable[Selected], size: int) -> dict[KeyRange, list[Selected]]:
    out: dict[KeyRange, list[Selected]] = {}
    for s in sorted(selection, key=lambda s: s.key):
        out.setdefault(KeyRange.containing(s.key.number, size), []).append(s)
    return dict(sorted(out.items(), key=lambda kv: kv[0].start))


def _identifier(slug: str, r: KeyRange) -> str:
    return f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, f'gti:{slug}:{r.start}-{r.end}')}"


def _book(
    store: NovelStore,
    meta: NovelMeta,
    chapters: list[Selected],
    cover: bytes | None,
    identifier: str,
    series_index: int,
) -> epub.EpubBook:
    book = epub.EpubBook()
    book.set_identifier(identifier)
    book.set_title(f"{meta.title} {chapters[0].key.label}–{chapters[-1].key.label}")
    book.set_language(meta.language)
    if meta.author:
        book.add_author(meta.author)
    for tag in meta.tags:
        book.add_metadata("DC", "subject", tag)
    # Series, for Calibre (OPF 2 meta) and for EPUB 3 readers (belongs-to-collection).
    book.add_metadata(None, "meta", "", {"name": "calibre:series", "content": meta.title})
    book.add_metadata(None, "meta", "", {"name": "calibre:series_index", "content": str(series_index)})
    book.add_metadata(None, "meta", meta.title, {"property": "belongs-to-collection", "id": "series"})
    book.add_metadata(None, "meta", "series", {"refines": "#series", "property": "collection-type"})
    book.add_metadata(None, "meta", str(series_index), {"refines": "#series", "property": "group-position"})

    style = epub.EpubItem(uid="style", file_name="style/book.css", media_type="text/css", content=_CSS)
    book.add_item(style)
    items = []
    for s in chapters:
        version = store.read_version(s.version_id)
        heading = chapter_heading(s.key, version.title)
        body = Markup("\n").join(render.block_html(b, remote_images=False) for b in version.blocks)
        item = epub.EpubHtml(title=heading, file_name=f"{anchor(s.key)}.xhtml", lang=meta.language)
        item.content = Markup('<h2 class="chapter">{}</h2>\n{}').format(heading, body)
        item.add_item(style)
        book.add_item(item)
        items.append(item)

    spine: list = ["nav", *items]
    if cover:
        book.set_cover("cover.png" if cover.startswith(b"\x89PNG") else "cover.jpg", cover)
        spine.insert(0, "cover")
    book.toc = items
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = spine
    return book


def _write(path: Path, book: epub.EpubBook) -> None:
    """Write atomically, so an interrupted build never leaves half a book."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    epub.write_epub(str(tmp), book)
    os.replace(tmp, path)

