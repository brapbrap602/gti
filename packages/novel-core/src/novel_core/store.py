"""NovelStore: the single owner of one novel's facts.

A novel lives in its own directory: `novel.sqlite` plus `raw/`, the compressed
pages its versions were normalized from. Every public method is one transaction.
Chapter keys are never stored on items or versions; they are derived on read from
each source's alignment rules, so editing those rules moves everything with them.
Only output rows record a key (`built_key`), the key their artifact was built for.

Concurrency: WAL with a 5 s busy timeout; each thread uses its own connection.
"""

import hashlib
import json
import sqlite3
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Self

import sqlalchemy as sa
import zstandard

from novel_core.alignment import AlignmentRules
from novel_core.blocks import blocks_from_json, blocks_to_json, content_hash
from novel_core.build import BuildPlan, OutputKind, OutputRow, VolumeRow
from novel_core.check import CheckReport
from novel_core.finding import Finding
from novel_core.keys import ChapterKey, ItemRef, KeyRange, parse_printed
from novel_core.model import (
    AlignmentDiff,
    IndexDiff,
    Inserted,
    ItemStatus,
    Kind,
    Moved,
    NewVersion,
    NovelMeta,
    PutResult,
    RawChapter,
    SourceInfo,
    SourceItem,
    SourceSpec,
    Unchanged,
    Version,
)
from novel_core.selection import Pin, Selected, SourceId, rank, unpinned
from novel_core.view import CurrentVersion, NovelView, StoreError, StoredItem, derive

SCHEMA_VERSION = 4
DB_NAME = "novel.sqlite"

type Clock = Callable[[], datetime]


_md = sa.MetaData()
_novel = sa.Table(
    "novel", _md,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("title", sa.String, nullable=False),
    sa.Column("author", sa.String),
    sa.Column("language", sa.String, nullable=False),
    sa.Column("status", sa.String),
    sa.Column("cover_path", sa.String),
    sa.Column("tags_json", sa.String, nullable=False),
    sa.Column("priority_json", sa.String, nullable=False),
)  # fmt: skip
_source = sa.Table(
    "source", _md,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("backend", sa.String, nullable=False),
    sa.Column("url", sa.String, nullable=False),
    sa.Column("lang", sa.String, nullable=False),
    sa.Column("kind", sa.String, nullable=False),
    sa.Column("alignment_json", sa.String, nullable=False),
    sa.Column("config_json", sa.String, nullable=False),
    sa.Column("published", sa.Boolean, nullable=False, server_default=sa.text("1")),
    sa.UniqueConstraint("backend", "url"),
)  # fmt: skip
_item = sa.Table(
    "source_item", _md,
    sa.Column("source_id", sa.ForeignKey("source.id"), primary_key=True),
    sa.Column("item_ref", sa.String, primary_key=True),
    sa.Column("position", sa.Integer, nullable=False),
    sa.Column("printed_number", sa.Integer),
    sa.Column("part", sa.Integer, nullable=False),
    sa.Column("title", sa.String, nullable=False),
    sa.Column("status", sa.String, nullable=False),
    sa.Column("reason", sa.String),
    sa.Column("vanished", sa.Boolean, nullable=False),
    sa.Column("last_seen_at", sa.String, nullable=False),
)  # fmt: skip
_version = sa.Table(
    "version", _md,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("source_id", sa.ForeignKey("source.id"), nullable=False),
    sa.Column("item_ref", sa.String, nullable=False),
    sa.Column("title", sa.String, nullable=False),
    sa.Column("blocks_json", sa.String, nullable=False),
    sa.Column("content_hash", sa.String, nullable=False),
    sa.Column("first_seen_at", sa.String, nullable=False),
    sa.Column("last_seen_at", sa.String, nullable=False),
    sa.Column("provenance_json", sa.String, nullable=False),
    sa.Column("raw_path", sa.String),
    sa.Column("rules_rev", sa.String),
    sa.Column("raw_hash", sa.String),
    sa.UniqueConstraint("source_id", "item_ref", "content_hash"),
)  # fmt: skip
_finding = sa.Table(
    "finding", _md,
    sa.Column("version_id", sa.ForeignKey("version.id", ondelete="CASCADE"), primary_key=True),
    sa.Column("check", sa.String, primary_key=True),
    sa.Column("detail", sa.String, nullable=False),
)  # fmt: skip
# The user's word that the checks in checks_json are false positives for one kept raw of one item.
_release = sa.Table(
    "release", _md,
    sa.Column("source_id", sa.ForeignKey("source.id"), primary_key=True),
    sa.Column("item_ref", sa.String, primary_key=True),
    sa.Column("raw_hash", sa.String, primary_key=True),  # "" for a version stored without a raw
    sa.Column("checks_json", sa.String, nullable=False),
    sa.Column("released_at", sa.String, nullable=False),
)  # fmt: skip
_pin = sa.Table(
    "pin", _md,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("range_start", sa.Integer, nullable=False),
    sa.Column("range_end", sa.Integer, nullable=False),
    sa.Column("source_id", sa.ForeignKey("source.id"), nullable=False),
)  # fmt: skip
_output = sa.Table(
    "output", _md,
    sa.Column("kind", sa.String, primary_key=True),
    sa.Column("key_number", sa.Integer, primary_key=True),
    sa.Column("key_part", sa.Integer, primary_key=True),
    sa.Column("source_id", sa.ForeignKey("source.id"), nullable=False),
    sa.Column("item_ref", sa.String, nullable=False),
    sa.Column("version_hash", sa.String, nullable=False),
    sa.Column("fingerprint", sa.String, nullable=False),
    sa.Column("artifact", sa.String, nullable=False),
    sa.Column("built_at", sa.String, nullable=False),
    sa.Column("legacy", sa.Boolean, nullable=False),
)  # fmt: skip
_volume = sa.Table(
    "volume", _md,
    sa.Column("range_start", sa.Integer, primary_key=True),
    sa.Column("range_end", sa.Integer, primary_key=True),
    sa.Column("membership_hash", sa.String, nullable=False),
    sa.Column("artifact", sa.String, nullable=False),
    sa.Column("built_at", sa.String, nullable=False),
)  # fmt: skip


def _add_volumes(conn: sa.Connection) -> None:
    _volume.create(conn)


def _add_published(conn: sa.Connection) -> None:
    # Same DDL as the column above, so created and migrated stores match; existing sources stay published.
    conn.exec_driver_sql("ALTER TABLE source ADD COLUMN published BOOLEAN NOT NULL DEFAULT 1")


def _add_checks(conn: sa.Connection) -> None:
    # Same DDL as the columns above; raw_hash is read back from the kept raw's file name (see _write_raw).
    conn.exec_driver_sql("ALTER TABLE version ADD COLUMN rules_rev VARCHAR")
    conn.exec_driver_sql("ALTER TABLE version ADD COLUMN raw_hash VARCHAR")
    for r in conn.execute(sa.select(_version.c.id, _version.c.raw_path).where(_version.c.raw_path.is_not(None))).all():
        conn.execute(_version.update().where(_version.c.id == r.id).values(raw_hash=_raw_hash_of(r.raw_path)))
    _finding.create(conn)
    _release.create(conn)


# Each step upgrades a store from the version it is keyed by to the next one.
_MIGRATIONS: dict[int, Callable[[sa.Connection], None]] = {1: _add_volumes, 2: _add_published, 3: _add_checks}


def stored_schema(novel_dir: Path) -> int:
    """The schema version of a novel's database as stored, read without migrating it."""
    db = novel_dir / DB_NAME
    if not db.exists():
        raise FileNotFoundError(db)
    with closing(sqlite3.connect(db)) as conn:
        return conn.execute("PRAGMA user_version").fetchone()[0]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _engine(db: Path) -> sa.Engine:
    engine = sa.create_engine(f"sqlite:///{db}")

    @sa.event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    return engine


class NovelStore:
    def __init__(self, novel_dir: Path, engine: sa.Engine, clock: Clock):
        self._dir = novel_dir
        self._engine = engine
        self._clock = clock

    # -- lifecycle ---------------------------------------------------------

    @classmethod
    def create(cls, novel_dir: Path, meta: NovelMeta, clock: Clock = _utc_now) -> Self:
        db = novel_dir / DB_NAME
        if db.exists():
            raise FileExistsError(db)
        novel_dir.mkdir(parents=True, exist_ok=True)
        engine = _engine(db)
        with engine.begin() as conn:
            _md.create_all(conn)
            conn.exec_driver_sql(f"PRAGMA user_version={SCHEMA_VERSION}")
            conn.execute(_novel.insert().values(id=1, **_meta_row(meta), priority_json="[]"))
        return cls(novel_dir, engine, clock)

    @classmethod
    def open(cls, novel_dir: Path, clock: Clock = _utc_now) -> Self:
        db = novel_dir / DB_NAME
        if not db.exists():
            raise FileNotFoundError(db)
        engine = _engine(db)
        with engine.begin() as conn:
            version = conn.exec_driver_sql("PRAGMA user_version").scalar()
            while version in _MIGRATIONS:
                _MIGRATIONS[version](conn)
                version += 1
                conn.exec_driver_sql(f"PRAGMA user_version={version}")
        if version != SCHEMA_VERSION:
            engine.dispose()
            raise StoreError(f"{db}: schema version {version}, expected {SCHEMA_VERSION}")
        return cls(novel_dir, engine, clock)

    def close(self) -> None:
        self._engine.dispose()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @property
    def folder(self) -> Path:
        """The novel's folder; in a library its name is the novel's slug."""
        return self._dir

    # -- novel and sources -------------------------------------------------

    @property
    def meta(self) -> NovelMeta:
        with self._engine.connect() as conn:
            return _load_meta(conn)

    def set_meta(self, meta: NovelMeta) -> None:
        with self._engine.begin() as conn:
            conn.execute(_novel.update().values(**_meta_row(meta)))

    def upsert_source(self, spec: SourceSpec, *, published: bool = True) -> SourceId:
        """Add a source, or update the spec of the one with the same (backend, url).

        `published` applies only when the source is new; a repeat upsert never changes it.
        """
        values = {"lang": spec.lang, "kind": str(spec.kind), "config_json": json.dumps(dict(spec.config), sort_keys=True)}
        with self._engine.begin() as conn:
            existing = conn.execute(
                sa.select(_source.c.id).where(_source.c.backend == spec.backend, _source.c.url == spec.url)
            ).scalar()
            if existing is not None:
                conn.execute(_source.update().where(_source.c.id == existing).values(**values))
                return existing
            return conn.execute(
                _source.insert().values(
                    backend=spec.backend, url=spec.url, alignment_json=AlignmentRules().to_json(),
                    published=published, **values,
                )  # fmt: skip
            ).inserted_primary_key[0]

    def sources(self) -> tuple[SourceInfo, ...]:
        with self._engine.connect() as conn:
            return tuple(_load_sources(conn).values())

    def item_refs(self, source: SourceId) -> frozenset[ItemRef]:
        """Every item the source's index has listed, vanished ones included."""
        with self._engine.connect() as conn:
            rows = conn.execute(sa.select(_item.c.item_ref).where(_item.c.source_id == source))
            return frozenset(r.item_ref for r in rows)

    def set_priority(self, sources: Sequence[SourceId]) -> None:
        with self._engine.begin() as conn:
            known = _load_sources(conn)
            if unknown := [s for s in sources if s not in known]:
                raise StoreError(f"unknown sources {unknown}")
            conn.execute(_novel.update().values(priority_json=json.dumps(list(sources))))

    def set_published(self, source: SourceId, on: bool) -> None:
        """Switch a source in or out of the book. Unpublishing a pinned source is refused."""
        with self._engine.begin() as conn:
            self._require_source(conn, source)
            if not on:
                _, pins = _load_policy(conn)
                if ranges := [f"{p.range.start}-{p.range.end}" for p in pins if p.source_id == source]:
                    raise StoreError(f"source {source} is pinned at {', '.join(ranges)}; unpin it first")
            conn.execute(_source.update().where(_source.c.id == source).values(published=on))

    def priority(self) -> tuple[SourceId, ...]:
        """Every source, best first; sources missing from the stored list rank after it, by id."""
        with self._engine.connect() as conn:
            priority, _ = _load_policy(conn)
            return tuple(rank(priority, _load_sources(conn)))

    def set_pin(self, keys: KeyRange, source: SourceId) -> None:
        """Pin numbers keys.start..keys.end to a source. A later pin wins where pins overlap."""
        with self._engine.begin() as conn:
            info = _load_sources(conn).get(source)
            if info is None:
                raise StoreError(f"unknown source {source}")
            if info.spec.kind is Kind.RAW_ZH:
                raise StoreError(f"source {source} is raw-zh and can never be published")
            if not info.published:
                raise StoreError(f"source {source} is unpublished; publish it before pinning")
            conn.execute(_pin.insert().values(range_start=keys.start, range_end=keys.end, source_id=source))

    def unpin(self, keys: KeyRange) -> tuple[Pin, ...]:
        """Return numbers keys.start..keys.end to priority order; returns the pins left, oldest first.

        A pin partly inside keys keeps its other numbers, and every pin keeps its precedence.
        Raises StoreError if no pin covers any of these numbers.
        """
        with self._engine.begin() as conn:
            _, pins = _load_policy(conn)
            kept = unpinned(pins, keys)
            if kept == pins:
                raise StoreError(f"nothing in {keys.start}-{keys.end} is pinned")
            conn.execute(_pin.delete())  # rewritten in order: ids are the precedence
            for p in kept:
                conn.execute(_pin.insert().values(range_start=p.range.start, range_end=p.range.end, source_id=p.source_id))
            return tuple(kept)

    # -- index and alignment -----------------------------------------------

    def record_index(self, source: SourceId, items: Sequence[SourceItem]) -> IndexDiff:
        """Store a source's full chapter list. Items are matched by ref, never by position.

        Refs missing from this index are marked vanished (their versions are kept but
        they get no key); a vanished ref that reappears is revived.
        """
        refs = [i.ref for i in items]
        if len(set(refs)) != len(refs):
            raise StoreError("duplicate refs in one index")
        now = self._now()
        with self._engine.begin() as conn:
            self._require_source(conn, source)
            existing = {
                r.item_ref: r.vanished
                for r in conn.execute(sa.select(_item.c.item_ref, _item.c.vanished).where(_item.c.source_id == source))
            }
            added, revived = [], []
            for item in items:
                number, part = parse_printed(item.title, item.ref if item.ref_numbered else "")
                values = {
                    "position": item.position,
                    "printed_number": item.number if item.number is not None else number,
                    "part": item.part if item.part is not None else part,
                    "title": item.title,
                    "vanished": False,
                    "last_seen_at": now,
                }
                if item.ref in existing:
                    if existing[item.ref]:
                        revived.append(item.ref)
                    conn.execute(_item.update().where(*_item_is(source, item.ref)).values(**values))
                else:
                    added.append(item.ref)
                    conn.execute(
                        _item.insert().values(source_id=source, item_ref=item.ref, status=ItemStatus.PENDING, **values)
                    )
            vanished = sorted(ref for ref, gone in existing.items() if not gone and ref not in set(refs))
            if vanished:
                conn.execute(
                    _item.update()
                    .where(_item.c.source_id == source, _item.c.item_ref.in_(vanished))
                    .values(vanished=True)
                )
        return IndexDiff(tuple(added), tuple(vanished), tuple(revived))

    def set_alignment(self, source: SourceId, rules: AlignmentRules) -> AlignmentDiff:
        with self._engine.begin() as conn:
            info = self._require_source(conn, source)
            items = _load_items(conn).get(source, [])
            before = derive(items, info).keys
            after = derive(items, replace(info, alignment=rules)).keys
            conn.execute(_source.update().where(_source.c.id == source).values(alignment_json=rules.to_json()))
        moved = [
            Moved(ref, before.get(ref), after.get(ref))
            for ref in sorted(before.keys() | after.keys())
            if before.get(ref) != after.get(ref)
        ]
        return AlignmentDiff(tuple(moved))

    def rebase_refs(self, source: SourceId, old_prefix: str, new_prefix: str) -> int:
        """Rewrite refs after a host changes its path layout; returns how many items moved.

        If the new ref already exists (a newer index recorded it), the old item's
        versions and outputs are merged into it and the old item row is dropped.
        """
        with self._engine.begin() as conn:
            info = self._require_source(conn, source)
            old_refs = [
                r for r in conn.execute(sa.select(_item.c.item_ref).where(_item.c.source_id == source)).scalars()
                if r.startswith(old_prefix)
            ]
            for old in old_refs:
                new = new_prefix + old[len(old_prefix) :]
                if new == old:
                    continue
                target_exists = conn.execute(sa.select(_item.c.item_ref).where(*_item_is(source, new))).first()
                if target_exists:
                    conn.execute(_item.delete().where(*_item_is(source, old)))
                else:
                    conn.execute(_item.update().where(*_item_is(source, old)).values(item_ref=new))
                self._move_versions(conn, source, old, new)
                self._move_releases(conn, source, old, new)
                conn.execute(
                    _output.update()
                    .where(_output.c.source_id == source, _output.c.item_ref == old)
                    .values(item_ref=new)
                )
            rules = info.alignment.rebased(old_prefix, new_prefix)
            conn.execute(_source.update().where(_source.c.id == source).values(alignment_json=rules.to_json()))
        return len(old_refs)

    def _move_versions(self, conn: sa.Connection, source: SourceId, old: ItemRef, new: ItemRef) -> None:
        clash = {
            r.content_hash: r
            for r in conn.execute(sa.select(_version).where(_version.c.source_id == source, _version.c.item_ref == new))
        }
        for v in conn.execute(sa.select(_version).where(_version.c.source_id == source, _version.c.item_ref == old)).all():
            if v.content_hash in clash:
                kept = clash[v.content_hash]
                conn.execute(
                    _version.update()
                    .where(_version.c.id == kept.id)
                    .values(last_seen_at=max(kept.last_seen_at, v.last_seen_at))
                )
                conn.execute(_version.delete().where(_version.c.id == v.id))
            else:
                conn.execute(_version.update().where(_version.c.id == v.id).values(item_ref=new))

    def _move_releases(self, conn: sa.Connection, source: SourceId, old: ItemRef, new: ItemRef) -> None:
        for r in conn.execute(sa.select(_release).where(*_release_is(source, old))).all():
            _record_release(conn, source, new, r.raw_hash, json.loads(r.checks_json), r.released_at)
        conn.execute(_release.delete().where(*_release_is(source, old)))

    # -- versions ----------------------------------------------------------

    def put_version(self, source: SourceId, item_ref: ItemRef, v: NewVersion) -> PutResult:
        """Store a chapter text. Identical text (title + blocks) is stored once and made current again.

        The stored row ends up naming this put's raw (when given), so a current version's findings
        are always those of the raw it names. Its findings and rules_rev are replaced only when
        v.rules_rev is given: a put without checks never clears a hold.
        """
        digest = content_hash(v.title, v.blocks)
        now = self._now()
        with self._engine.begin() as conn:
            if conn.execute(sa.select(_item.c.item_ref).where(*_item_is(source, item_ref))).first() is None:
                raise StoreError(f"unknown item {item_ref!r} in source {source}; record_index first")
            conn.execute(_item.update().where(*_item_is(source, item_ref)).values(status=ItemStatus.OK, reason=None))
            existing = conn.execute(
                sa.select(_version.c.id, _version.c.provenance_json).where(
                    _version.c.source_id == source,
                    _version.c.item_ref == item_ref,
                    _version.c.content_hash == digest,
                )
            ).first()
            if existing is not None:
                values: dict = {"last_seen_at": now}
                if v.raw is not None:
                    provenance = json.loads(existing.provenance_json) | _raw_provenance(v.raw)
                    values |= self._keep_raw(source, item_ref, v.raw)
                    values["provenance_json"] = json.dumps(provenance, sort_keys=True, ensure_ascii=False)
                if v.rules_rev is not None:
                    values["rules_rev"] = v.rules_rev
                    conn.execute(_finding.delete().where(_finding.c.version_id == existing.id))
                    _insert_findings(conn, existing.id, v.findings)
                conn.execute(_version.update().where(_version.c.id == existing.id).values(**values))
                return Unchanged(existing.id, digest)
            provenance = dict(v.provenance)
            raw = {"raw_path": None, "raw_hash": None}
            if v.raw is not None:
                raw = self._keep_raw(source, item_ref, v.raw)
                provenance |= _raw_provenance(v.raw)
            version_id = conn.execute(
                _version.insert().values(
                    source_id=source,
                    item_ref=item_ref,
                    title=v.title,
                    blocks_json=blocks_to_json(v.blocks),
                    content_hash=digest,
                    first_seen_at=now,
                    last_seen_at=now,
                    provenance_json=json.dumps(provenance, sort_keys=True, ensure_ascii=False),
                    rules_rev=v.rules_rev,
                    **raw,
                )
            ).inserted_primary_key[0]
            _insert_findings(conn, version_id, v.findings)
        return Inserted(version_id, digest)

    def _keep_raw(self, source: SourceId, item_ref: ItemRef, raw: RawChapter) -> dict[str, str]:
        """Write the raw if it is new; returns the version columns that name it."""
        path = self._write_raw(source, item_ref, raw)
        return {"raw_path": path, "raw_hash": _raw_hash_of(path)}

    def _write_raw(self, source: SourceId, item_ref: ItemRef, raw: RawChapter) -> str:
        data = raw.content.encode("utf-8")
        name = f"{_sha1(item_ref.encode())}-{_sha1(data)[:12]}.{raw.content_type}.zst"
        rel = Path("raw") / str(source) / name
        path = self._dir / rel
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(zstandard.ZstdCompressor(level=10).compress(data))
            tmp.replace(path)
        return rel.as_posix()

    def release(self, source: SourceId, refs: Sequence[ItemRef]) -> dict[ItemRef, tuple[str, ...]]:
        """Record that the checks firing now on these items' current versions are false positives.

        A release covers one kept raw (the current version's raw hash) and the checks named in it,
        so a reclean of the same raw keeps it, while a new raw or a new kind of finding holds the
        item again. Returns the checks released per ref; refs with no finding are left out.
        """
        now = self._now()
        released: dict[ItemRef, tuple[str, ...]] = {}
        with self._engine.begin() as conn:
            self._require_source(conn, source)
            for ref in refs:
                v = conn.execute(
                    sa.select(_version.c.id, _version.c.raw_hash)
                    .where(_version.c.source_id == source, _version.c.item_ref == ref)
                    .order_by(_version.c.last_seen_at.desc(), _version.c.id.desc())
                    .limit(1)
                ).first()
                if v is None:
                    raise StoreError(f"no stored text for {ref!r} in source {source}")
                checks = conn.execute(sa.select(_finding.c.check).where(_finding.c.version_id == v.id)).scalars().all()
                if checks:
                    released[ref] = tuple(sorted(checks))
                    _record_release(conn, source, ref, v.raw_hash or "", checks, now)
        return released

    def mark_item(self, source: SourceId, item_ref: ItemRef, status: ItemStatus, reason: str | None = None) -> None:
        with self._engine.begin() as conn:
            done = conn.execute(_item.update().where(*_item_is(source, item_ref)).values(status=status, reason=reason))
            if done.rowcount == 0:
                raise StoreError(f"unknown item {item_ref!r} in source {source}")

    def read_raw(self, version_id: int) -> RawChapter | None:
        """The kept page a version was made from; None if it was stored without one."""
        with self._engine.connect() as conn:
            r = conn.execute(
                sa.select(_version.c.raw_path, _version.c.provenance_json).where(_version.c.id == version_id)
            ).one_or_none()
        if r is None:
            raise StoreError(f"unknown version {version_id}")
        if r.raw_path is None:
            return None
        provenance = json.loads(r.provenance_json)
        fetched_at = provenance.get("fetched_at")
        return RawChapter(
            zstandard.ZstdDecompressor().decompress((self._dir / r.raw_path).read_bytes()).decode("utf-8"),
            r.raw_path.rsplit(".", 2)[1],  # <sha1(ref)>-<hash>.<type>.zst
            provenance.get("final_url"),
            datetime.fromisoformat(fetched_at) if fetched_at else None,
        )

    def read_version(self, version_id: int) -> Version:
        with self._engine.connect() as conn:
            r = conn.execute(sa.select(_version).where(_version.c.id == version_id)).one_or_none()
        if r is None:
            raise StoreError(f"unknown version {version_id}")
        return Version(
            r.id, r.source_id, r.item_ref, r.title, blocks_from_json(r.blocks_json), r.content_hash,
            json.loads(r.provenance_json),
        )  # fmt: skip

    # -- selection, builds, checks -----------------------------------------

    def view(self) -> NovelView:
        """A read of the whole novel that answers every derived question consistently (see NovelView)."""
        with self._engine.connect() as conn:
            latest: dict[tuple[SourceId, ItemRef], sa.Row] = {}
            for v in conn.execute(
                sa.select(_version.c.id, _version.c.source_id, _version.c.item_ref, _version.c.content_hash,
                          _version.c.title, _version.c.last_seen_at, _version.c.rules_rev, _version.c.raw_hash)
            ):  # fmt: skip
                k = (v.source_id, v.item_ref)
                if k not in latest or (v.last_seen_at, v.id) > (latest[k].last_seen_at, latest[k].id):
                    latest[k] = v
            findings: dict[int, list[Finding]] = defaultdict(list)
            for f in conn.execute(sa.select(_finding).order_by(_finding.c.version_id, _finding.c.check)):
                findings[f.version_id].append(Finding(f.check, f.detail))
            priority, pins = _load_policy(conn)
            return NovelView(
                _load_meta(conn),
                _load_sources(conn),
                _load_items(conn),
                [
                    CurrentVersion(
                        v.source_id, v.item_ref, v.id, v.content_hash, v.title, v.rules_rev,
                        tuple(findings.get(v.id, ())), v.raw_hash,
                    )  # fmt: skip
                    for v in latest.values()
                ],
                priority,
                pins,
                {kind: _load_outputs(conn, kind) for kind in OutputKind},
                {
                    (r.source_id, r.item_ref, r.raw_hash): frozenset(json.loads(r.checks_json))
                    for r in conn.execute(sa.select(_release))
                },
            )

    def selection(self) -> tuple[Selected, ...]:
        """The publishable book: one source per number (pins, then priority), never raw-zh."""
        return self.view().selection

    def chapters(self, source: SourceId) -> tuple[Selected, ...]:
        """Every mapped item of one source with its current version, selected or not, in key order."""
        return self.view().chapters(source)

    def to_fetch(
        self, source: SourceId, refresh: KeyRange | None = None, only: KeyRange | None = None
    ) -> tuple[ItemRef, ...]:
        """The items a sync of this source should fetch, in index order (see NovelView.to_fetch)."""
        return self.view().to_fetch(source, refresh, only)

    def outputs(self, kind: OutputKind) -> tuple[OutputRow, ...]:
        with self._engine.connect() as conn:
            return _load_outputs(conn, kind)

    def plan_build(self, kind: OutputKind, fingerprint: str, force: KeyRange | None = None) -> BuildPlan:
        return self.view().plan_build(kind, fingerprint, force)

    def record_output(
        self, kind: OutputKind, selected: Selected, fingerprint: str, artifact: str, legacy: bool = False
    ) -> None:
        """Record a built artifact for selected.key, replacing whatever was built for that key."""
        values = {
            "source_id": selected.source_id,
            "item_ref": selected.item_ref,
            "version_hash": selected.content_hash,
            "fingerprint": fingerprint,
            "artifact": artifact,
            "built_at": self._now(),
            "legacy": legacy,
        }
        with self._engine.begin() as conn:
            conn.execute(_output.delete().where(*_output_is(kind, selected.key)))
            conn.execute(
                _output.insert().values(
                    kind=str(kind), key_number=selected.key.number, key_part=selected.key.part, **values
                )
            )

    def prune_output(self, kind: OutputKind, key: ChapterKey) -> None:
        with self._engine.begin() as conn:
            conn.execute(_output.delete().where(*_output_is(kind, key)))

    def volumes(self) -> tuple[VolumeRow, ...]:
        with self._engine.connect() as conn:
            return tuple(
                VolumeRow(KeyRange(r.range_start, r.range_end), r.membership_hash, r.artifact)
                for r in conn.execute(sa.select(_volume).order_by(_volume.c.range_start, _volume.c.range_end))
            )

    def record_volume(self, volume: VolumeRow) -> None:
        """Record a built volume, replacing whatever was built for the same range."""
        with self._engine.begin() as conn:
            conn.execute(_volume.delete().where(*_volume_is(volume.range)))
            conn.execute(
                _volume.insert().values(
                    range_start=volume.range.start,
                    range_end=volume.range.end,
                    membership_hash=volume.membership_hash,
                    artifact=volume.artifact,
                    built_at=self._now(),
                )
            )

    def prune_volume(self, keys: KeyRange) -> None:
        with self._engine.begin() as conn:
            conn.execute(_volume.delete().where(*_volume_is(keys)))

    def check(self) -> CheckReport:
        return self.view().check()

    # -- internals ---------------------------------------------------------

    def _now(self) -> str:
        return self._clock().astimezone(UTC).isoformat(timespec="microseconds")

    def _require_source(self, conn: sa.Connection, source: SourceId) -> SourceInfo:
        info = _load_sources(conn).get(source)
        if info is None:
            raise StoreError(f"unknown source {source}")
        return info


# -- row helpers -------------------------------------------------------------


def _sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def _raw_hash_of(raw_path: str) -> str:
    """A kept raw's identity: the sha1 prefix of its content, from its name <sha1(ref)>-<hash>.<type>.zst."""
    return raw_path.rsplit("/", 1)[-1].split(".", 1)[0].split("-", 1)[1]


def _raw_provenance(raw: RawChapter) -> dict:
    return {
        "content_type": raw.content_type,
        "final_url": raw.final_url,
        "fetched_at": raw.fetched_at.isoformat() if raw.fetched_at else None,
    }


def _release_is(source: SourceId, ref: ItemRef):
    return _release.c.source_id == source, _release.c.item_ref == ref


def _record_release(
    conn: sa.Connection, source: SourceId, ref: ItemRef, raw_hash: str, checks: Iterable[str], at: str
) -> None:
    """Add checks to the release of (source, ref, raw_hash); checks released before stay released."""
    where = (*_release_is(source, ref), _release.c.raw_hash == raw_hash)
    before = conn.execute(sa.select(_release.c.checks_json).where(*where)).scalar()
    merged = sorted(set(checks) | set(json.loads(before) if before else ()))
    conn.execute(_release.delete().where(*where))
    conn.execute(
        _release.insert().values(
            source_id=source, item_ref=ref, raw_hash=raw_hash, checks_json=json.dumps(merged), released_at=at
        )
    )


def _insert_findings(conn: sa.Connection, version_id: int, findings: Sequence[Finding]) -> None:
    if findings:
        conn.execute(_finding.insert(), [{"version_id": version_id, "check": f.check, "detail": f.detail} for f in findings])


def _meta_row(meta: NovelMeta) -> dict:
    return {
        "title": meta.title,
        "author": meta.author,
        "language": meta.language,
        "status": meta.status,
        "cover_path": meta.cover_path,
        "tags_json": json.dumps(list(meta.tags)),
    }


def _item_is(source: SourceId, ref: ItemRef):
    return _item.c.source_id == source, _item.c.item_ref == ref


def _output_is(kind: OutputKind, key: ChapterKey):
    return _output.c.kind == str(kind), _output.c.key_number == key.number, _output.c.key_part == key.part


def _volume_is(keys: KeyRange):
    return _volume.c.range_start == keys.start, _volume.c.range_end == keys.end


def _load_meta(conn: sa.Connection) -> NovelMeta:
    r = conn.execute(sa.select(_novel)).one()
    return NovelMeta(r.title, r.author, r.language, r.status, r.cover_path, tuple(json.loads(r.tags_json)))


def _load_sources(conn: sa.Connection) -> dict[SourceId, SourceInfo]:
    return {
        r.id: SourceInfo(
            r.id,
            SourceSpec(r.backend, r.url, r.lang, Kind(r.kind), json.loads(r.config_json)),
            AlignmentRules.from_json(r.alignment_json),
            r.published,
        )
        for r in conn.execute(sa.select(_source).order_by(_source.c.id))
    }


def _load_items(conn: sa.Connection) -> dict[SourceId, list[StoredItem]]:
    items: dict[SourceId, list[StoredItem]] = defaultdict(list)
    for r in conn.execute(sa.select(_item).order_by(_item.c.source_id, _item.c.position)):
        items[r.source_id].append(
            StoredItem(r.source_id, r.item_ref, r.title, r.printed_number, r.part, ItemStatus(r.status), r.reason, r.vanished)
        )
    return items


def _load_policy(conn: sa.Connection) -> tuple[list[SourceId], list[Pin]]:
    priority = json.loads(conn.execute(sa.select(_novel.c.priority_json)).scalar())
    pins = [
        Pin(KeyRange(r.range_start, r.range_end), r.source_id)
        for r in conn.execute(sa.select(_pin).order_by(_pin.c.id))
    ]
    return priority, pins


def _load_outputs(conn: sa.Connection, kind: OutputKind) -> tuple[OutputRow, ...]:
    return tuple(
        OutputRow(
            OutputKind(r.kind),
            ChapterKey(r.key_number, r.key_part),
            r.source_id,
            r.item_ref,
            r.version_hash,
            r.fingerprint,
            r.artifact,
            r.legacy,
        )
        for r in conn.execute(
            sa.select(_output).where(_output.c.kind == str(kind)).order_by(_output.c.key_number, _output.c.key_part)
        )
    )
