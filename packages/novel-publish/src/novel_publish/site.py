"""The static site: a library page plus one reading page per range of chapter numbers.

The site directory is owned by `build_site`: it holds exactly the pages the
current selections call for. A page is rebuilt when one of its chapters is
stale (new, changed, re-selected or pruned, as `NovelStore.plan_build` reports),
when its file is missing, or when a neighbouring page appeared or disappeared
(its prev/next links changed). Everything else is left untouched.
"""

import hashlib
import os
import re
import shutil
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from importlib import resources
from pathlib import Path

import jinja2
from markupsafe import Markup
from novel_core import ChapterKey, Kind, KeyRange, NovelStore, OutputKind, Selected, chapter_heading

from novel_publish import render

PAGE_SIZE = 50  # chapter numbers per reading page
NOVELS = "novels"
ASSETS = "assets"


@dataclass(frozen=True)
class NovelBuild:
    slug: str
    chapters: int
    pages_written: int
    pages_deleted: int
    raw_only: bool


@dataclass(frozen=True)
class SiteReport:
    novels: tuple[NovelBuild, ...]


def build_site(novels: Mapping[str, NovelStore], out_dir: Path, force: bool = False) -> SiteReport:
    """Build the whole library (every novel, by slug) into out_dir, incrementally unless `force`.

    Folders of novels that are no longer in `novels` are removed.
    """
    fp = fingerprint()
    out_dir.mkdir(parents=True, exist_ok=True)
    _copy_assets(out_dir / ASSETS)
    (out_dir / ".nojekyll").touch()

    builds, cards = [], []
    for slug, store in sorted(novels.items()):
        build, card = _build_novel(slug, store, out_dir / NOVELS / slug, fp, force)
        builds.append(build)
        cards.append(card)
    for stale in _subdirs(out_dir / NOVELS) - set(novels):
        shutil.rmtree(out_dir / NOVELS / stale)
    _write(out_dir / "index.html", _env().get_template("library.html").render(novels=cards))
    return SiteReport(tuple(builds))


@cache
def fingerprint() -> str:
    """Changes whenever the templates, assets, page size or this renderer change."""
    h = hashlib.sha256(f"page_size={PAGE_SIZE}\n".encode())
    for module in (__file__, render.__file__):
        h.update(Path(module).read_bytes())
    for folder in ("templates", "static"):
        for f in sorted(resources.files(__package__).joinpath(folder).iterdir(), key=lambda f: f.name):
            h.update(f.name.encode() + b"\0" + f.read_bytes())
    return h.hexdigest()


# -- one novel --------------------------------------------------------------


@dataclass(frozen=True)
class _Page:
    start: int  # first chapter number of the range (the file name), not of its chapters
    chapters: tuple[Selected, ...]

    @property
    def filename(self) -> str:
        return f"{self.start}-{self.start + PAGE_SIZE - 1}.html"

    @property
    def label(self) -> str:
        return f"{self.chapters[0].key.label}–{self.chapters[-1].key.label}"


def _build_novel(slug: str, store: NovelStore, folder: Path, fp: str, force: bool) -> tuple[NovelBuild, dict]:
    meta = store.meta
    plan = store.plan_build(OutputKind.SITE, fp)
    pages = _paginate(store.selection())
    names = [p.filename for p in pages]

    existing = {f.name for f in folder.glob("*.html")} if folder.exists() else set()
    stale_starts = {_page_start(s.key) for s in plan.to_build} | {_page_start(r.built_key) for r in plan.to_prune}
    added = {i for i, n in enumerate(names) if n not in existing}
    removed_neighbours = _neighbours_of_removed(names, existing)
    rebuild = [
        i for i, p in enumerate(pages)
        if force or p.start in stale_starts or i in added or i in removed_neighbours
        or (i - 1) in added or (i + 1) in added
    ]  # fmt: skip

    template = _env().get_template("page.html")
    for i in rebuild:
        page = pages[i]
        html = template.render(
            novel=meta,
            page=page,
            prev=pages[i - 1] if i > 0 else None,
            next=pages[i + 1] if i + 1 < len(pages) else None,
            chapters=[_chapter_view(store, s) for s in page.chapters],
        )
        _write(folder / page.filename, html)
        for s in page.chapters:
            store.record_output(OutputKind.SITE, s, fp, f"{NOVELS}/{slug}/{page.filename}")
    for row in plan.to_prune:
        store.prune_output(OutputKind.SITE, row.built_key)
    deleted = existing - set(names)
    for name in deleted:
        (folder / name).unlink()

    raw_only = not pages and any(src.spec.kind is Kind.RAW_ZH for src in store.sources())
    card = {
        "title": meta.title,
        "author": meta.author,
        "chapters": sum(len(p.chapters) for p in pages),
        "raw_only": raw_only,
        "pages": [{"href": f"{NOVELS}/{slug}/{p.filename}", "label": p.label} for p in pages],
    }
    build = NovelBuild(slug, card["chapters"], len(rebuild), len(deleted), raw_only)
    return build, card


def _paginate(selection: Iterable[Selected]) -> list[_Page]:
    by_start: dict[int, list[Selected]] = {}
    for s in sorted(selection, key=lambda s: s.key):
        by_start.setdefault(_page_start(s.key), []).append(s)
    return [_Page(start, tuple(chapters)) for start, chapters in sorted(by_start.items())]


def _page_start(key: ChapterKey) -> int:
    """Chapter numbers 1-50 share page 1, 51-100 page 51, ...; 0 (a prologue override) joins page 1."""
    return KeyRange.containing(key.number, PAGE_SIZE).start


def _neighbours_of_removed(names: Sequence[str], existing: set[str]) -> set[int]:
    """Indexes of pages whose prev/next page was deleted: those next to where a removed file sorted."""
    def start(name: str) -> int:
        return int(name.split("-", 1)[0])

    starts = [start(n) for n in names]
    out: set[int] = set()
    for gone in existing - set(names):
        if not re.fullmatch(r"\d+-\d+\.html", gone):
            continue
        before = [i for i, s in enumerate(starts) if s < start(gone)]
        after = [i for i, s in enumerate(starts) if s > start(gone)]
        out.update(before[-1:] + after[:1])
    return out


# -- rendering --------------------------------------------------------------

def anchor(key: ChapterKey) -> str:
    return f"c{key.number}-{key.part}" if key.part else f"c{key.number}"


def _chapter_view(store: NovelStore, s: Selected) -> dict:
    version = store.read_version(s.version_id)
    return {
        "anchor": anchor(s.key),
        "heading": chapter_heading(s.key, version.title),
        "body": Markup("\n").join(render.block_html(b) for b in version.blocks),
    }


@cache
def _env() -> jinja2.Environment:
    return jinja2.Environment(
        loader=jinja2.PackageLoader(__package__, "templates"),
        autoescape=True,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )


# -- files ------------------------------------------------------------------


def _copy_assets(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for f in resources.files(__package__).joinpath("static").iterdir():
        target = folder / f.name
        data = f.read_bytes()
        if not target.exists() or target.read_bytes() != data:
            target.write_bytes(data)


def _write(path: Path, text: str) -> None:
    """Write atomically, so an interrupted build never leaves half a page."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def _subdirs(folder: Path) -> set[str]:
    return {d.name for d in folder.iterdir() if d.is_dir()} if folder.exists() else set()
