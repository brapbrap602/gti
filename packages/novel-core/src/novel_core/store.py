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
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Self

import sqlalchemy as sa
import zstandard

from novel_core.alignment import AlignmentRules, Derivation, Printed, derive_keys
from novel_core.blocks import blocks_from_json, blocks_to_json, content_hash
from novel_core.build import BuildPlan, OutputKind, OutputRow, VolumeRow, plan_build
from novel_core.check import CheckReport, Duplicate, ItemNote
from novel_core.keys import ChapterKey, ItemRef, KeyRange, parse_printed, title_number
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
from novel_core.selection import Pin, Selected, Selection, SourceId, rank, select

SCHEMA_VERSION = 2
DB_NAME = "novel.sqlite"

type Clock = Callable[[], datetime]


class StoreError(Exception):
    """A request the store refuses (unknown source or item, pin to a raw source, ...)."""


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
    sa.UniqueConstraint("source_id", "item_ref", "content_hash"),
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


# Each step upgrades a store from the version it is keyed by to the next one.
_MIGRATIONS: dict[int, Callable[[sa.Connection], None]] = {1: _add_volumes}


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


@dataclass(frozen=True)
class _Item:
    source_id: SourceId
    ref: ItemRef
    title: str
    printed_number: int | None
    part: int
    status: ItemStatus
    reason: str | None
    vanished: bool


@dataclass(frozen=True)
class _Snapshot:
    """Everything selection, planning and checks read, loaded in one transaction."""

    sources: dict[SourceId, SourceInfo]
    items: dict[SourceId, list[_Item]]
    derivations: dict[SourceId, Derivation]
    current: dict[SourceId, list[Selected]]  # current version of each mapped item that has one
    selection: Selection


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

    # -- novel and sources -------------------------------------------------

    @property
    def meta(self) -> NovelMeta:
        with self._engine.connect() as conn:
            r = conn.execute(sa.select(_novel)).one()
        return NovelMeta(r.title, r.author, r.language, r.status, r.cover_path, tuple(json.loads(r.tags_json)))

    def set_meta(self, meta: NovelMeta) -> None:
        with self._engine.begin() as conn:
            conn.execute(_novel.update().values(**_meta_row(meta)))

    def upsert_source(self, spec: SourceSpec) -> SourceId:
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
                    backend=spec.backend, url=spec.url, alignment_json=AlignmentRules().to_json(), **values
                )
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
            conn.execute(_pin.insert().values(range_start=keys.start, range_end=keys.end, source_id=source))

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
            before = _derive(items, info.alignment).keys
            after = _derive(items, rules).keys
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

    # -- versions ----------------------------------------------------------

    def put_version(self, source: SourceId, item_ref: ItemRef, v: NewVersion) -> PutResult:
        """Store a chapter text. Identical text (title + blocks) is stored once and made current again."""
        digest = content_hash(v.title, v.blocks)
        now = self._now()
        with self._engine.begin() as conn:
            if conn.execute(sa.select(_item.c.item_ref).where(*_item_is(source, item_ref))).first() is None:
                raise StoreError(f"unknown item {item_ref!r} in source {source}; record_index first")
            conn.execute(_item.update().where(*_item_is(source, item_ref)).values(status=ItemStatus.OK, reason=None))
            existing = conn.execute(
                sa.select(_version.c.id).where(
                    _version.c.source_id == source,
                    _version.c.item_ref == item_ref,
                    _version.c.content_hash == digest,
                )
            ).scalar()
            if existing is not None:
                conn.execute(_version.update().where(_version.c.id == existing).values(last_seen_at=now))
                return Unchanged(existing, digest)
            provenance = dict(v.provenance)
            raw_path = None
            if v.raw is not None:
                raw_path = self._write_raw(source, item_ref, v.raw)
                provenance |= {
                    "content_type": v.raw.content_type,
                    "final_url": v.raw.final_url,
                    "fetched_at": v.raw.fetched_at.isoformat() if v.raw.fetched_at else None,
                }
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
                    raw_path=raw_path,
                )
            ).inserted_primary_key[0]
        return Inserted(version_id, digest)

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

    def mark_item(self, source: SourceId, item_ref: ItemRef, status: ItemStatus, reason: str | None = None) -> None:
        with self._engine.begin() as conn:
            done = conn.execute(_item.update().where(*_item_is(source, item_ref)).values(status=status, reason=reason))
            if done.rowcount == 0:
                raise StoreError(f"unknown item {item_ref!r} in source {source}")

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

    def selection(self) -> tuple[Selected, ...]:
        """The publishable book: one source per number (pins, then priority), never raw-zh."""
        with self._engine.connect() as conn:
            return self._snapshot(conn).selection.chapters

    def chapters(self, source: SourceId) -> tuple[Selected, ...]:
        """Every mapped item of one source with its current version, selected or not, in key order."""
        with self._engine.connect() as conn:
            self._require_source(conn, source)
            return tuple(sorted(self._snapshot(conn).current.get(source, []), key=lambda s: s.key))

    def to_fetch(self, source: SourceId, refresh: KeyRange | None = None) -> tuple[ItemRef, ...]:
        """The items a sync of this source should fetch, in index order.

        An item is fetched when it has no version yet and the book lacks its number:
        no other source has a text for it (for a raw-zh source, no other raw text).
        Unmapped items without a version are fetched too, so their text can show what
        they are. Unavailable (locked), vanished and skipped items are left alone.
        Items whose key falls in `refresh` are fetched again whatever they hold.
        """
        with self._engine.connect() as conn:
            info = self._require_source(conn, source)
            snap = self._snapshot(conn)
            stored = set(
                conn.execute(sa.select(_version.c.item_ref).where(_version.c.source_id == source).distinct()).scalars()
            )
        if info.spec.kind is Kind.RAW_ZH:
            raws = (c for sid, c in snap.current.items() if snap.sources[sid].spec.kind is Kind.RAW_ZH)
            covered = {s.key.number for chapters in raws for s in chapters}
        else:
            covered = {s.key.number for s in snap.selection.chapters}
        keys = snap.derivations[source].keys
        wanted = []
        for item in snap.items.get(source, []):
            if item.vanished or item.ref in info.alignment.skip:
                continue
            key = keys.get(item.ref)
            if refresh is not None and key is not None and key.number in refresh:
                wanted.append(item.ref)
            elif item.ref not in stored and item.status is not ItemStatus.UNAVAILABLE:
                if key is None or key.number not in covered:
                    wanted.append(item.ref)
        return tuple(wanted)

    def outputs(self, kind: OutputKind) -> tuple[OutputRow, ...]:
        with self._engine.connect() as conn:
            return _load_outputs(conn, kind)

    def plan_build(self, kind: OutputKind, fingerprint: str, force: KeyRange | None = None) -> BuildPlan:
        with self._engine.connect() as conn:
            selection = self._snapshot(conn).selection.chapters
            return plan_build(selection, _load_outputs(conn, kind), fingerprint, force)

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
        with self._engine.connect() as conn:
            snap = self._snapshot(conn)
            legacy = [r for kind in OutputKind for r in _load_outputs(conn, kind) if r.legacy]
        return _report(snap, legacy)

    # -- internals ---------------------------------------------------------

    def _now(self) -> str:
        return self._clock().astimezone(UTC).isoformat(timespec="microseconds")

    def _require_source(self, conn: sa.Connection, source: SourceId) -> SourceInfo:
        info = _load_sources(conn).get(source)
        if info is None:
            raise StoreError(f"unknown source {source}")
        return info

    def _snapshot(self, conn: sa.Connection) -> _Snapshot:
        sources = _load_sources(conn)
        items = _load_items(conn)
        derivations = {sid: _derive(items.get(sid, []), info.alignment) for sid, info in sources.items()}

        latest: dict[tuple[SourceId, ItemRef], sa.Row] = {}
        for v in conn.execute(
            sa.select(_version.c.id, _version.c.source_id, _version.c.item_ref, _version.c.content_hash,
                      _version.c.title, _version.c.last_seen_at)
        ):  # fmt: skip
            k = (v.source_id, v.item_ref)
            if k not in latest or (v.last_seen_at, v.id) > (latest[k].last_seen_at, latest[k].id):
                latest[k] = v
        current: dict[SourceId, list[Selected]] = defaultdict(list)
        for (sid, ref), v in latest.items():
            key = derivations[sid].keys.get(ref)
            if key is not None:
                current[sid].append(Selected(key, sid, ref, v.id, v.content_hash, v.title))

        priority, pins = _load_policy(conn)
        publishable = {sid: c for sid, c in current.items() if sources[sid].spec.kind is not Kind.RAW_ZH}
        return _Snapshot(sources, items, derivations, dict(current), select(publishable, priority, pins))


# -- row helpers -------------------------------------------------------------


def _sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


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


def _load_sources(conn: sa.Connection) -> dict[SourceId, SourceInfo]:
    return {
        r.id: SourceInfo(
            r.id,
            SourceSpec(r.backend, r.url, r.lang, Kind(r.kind), json.loads(r.config_json)),
            AlignmentRules.from_json(r.alignment_json),
        )
        for r in conn.execute(sa.select(_source).order_by(_source.c.id))
    }


def _load_items(conn: sa.Connection) -> dict[SourceId, list[_Item]]:
    items: dict[SourceId, list[_Item]] = defaultdict(list)
    for r in conn.execute(sa.select(_item).order_by(_item.c.source_id, _item.c.position)):
        items[r.source_id].append(
            _Item(r.source_id, r.item_ref, r.title, r.printed_number, r.part, ItemStatus(r.status), r.reason, r.vanished)
        )
    return items


def _derive(items: Sequence[_Item], rules: AlignmentRules) -> Derivation:
    # Vanished items take no part in key derivation or duplicate detection.
    return derive_keys((Printed(i.ref, i.printed_number, i.part) for i in items if not i.vanished), rules)


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


def _report(snap: _Snapshot, legacy: Sequence[OutputRow]) -> CheckReport:
    raw = {sid for sid, info in snap.sources.items() if info.spec.kind is Kind.RAW_ZH}
    selected_numbers = {s.key.number for s in snap.selection.chapters}
    selected_by_key = {s.key: s for s in snap.selection.chapters}

    expected = {
        key.number for sid, d in snap.derivations.items() if sid not in raw for key in d.keys.values()
    } | selected_numbers
    gaps = sorted(set(range(min(expected), max(expected) + 1)) - selected_numbers) if expected else []
    raw_only = sorted(
        {c.key.number for sid in raw for c in snap.current.get(sid, [])} - selected_numbers
    )

    split_by_number: dict[int, set[bool]] = defaultdict(set)
    for sid, chapters in snap.current.items():
        if sid in raw:
            continue
        per_number: dict[int, bool] = defaultdict(bool)
        for c in chapters:
            per_number[c.key.number] |= c.key.part > 0
        for number, split in per_number.items():
            split_by_number[number].add(split)

    def notes(pred, detail=lambda _i: "") -> tuple[ItemNote, ...]:
        return tuple(
            ItemNote(i.source_id, i.ref, i.title, detail(i))
            for sid in sorted(snap.items)
            for i in snap.items[sid]
            if pred(i)
        )

    unmapped = {(sid, ref) for sid, d in snap.derivations.items() for ref in d.unmapped}
    moved = tuple(
        r for r in legacy if snap.derivations[r.source_id].keys.get(r.item_ref) != r.built_key
    )
    unselected = tuple(
        r
        for r in legacy
        if r not in moved
        and (
            (s := selected_by_key.get(r.built_key)) is None or (s.source_id, s.item_ref) != (r.source_id, r.item_ref)
        )
    )
    return CheckReport(
        gaps=tuple(gaps),
        raw_only=tuple(raw_only),
        duplicates=tuple(
            Duplicate(sid, key, refs)
            for sid, d in sorted(snap.derivations.items())
            for key, refs in sorted(d.duplicates.items())
        ),
        unmapped=notes(lambda i: (i.source_id, i.ref) in unmapped),
        vanished=notes(lambda i: i.vanished),
        failed=notes(lambda i: i.status is ItemStatus.FAILED, lambda i: i.reason or ""),
        title_mismatches=notes(
            lambda i: not i.vanished
            and i.printed_number is not None
            and (n := title_number(i.title)) is not None
            and n != i.printed_number,
            lambda i: str(title_number(i.title)),
        ),
        mixed_parts=tuple(sorted(n for n, splits in split_by_number.items() if len(splits) > 1)),
        pin_fallbacks=snap.selection.pin_fallbacks,
        legacy_moved=moved,
        legacy_unselected=unselected,
    )
