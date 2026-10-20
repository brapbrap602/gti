"""TranslateStore: the single owner of one novel's `translate.sqlite`.

It sits beside `novel.sqlite` and holds what translation adds to a novel: the
glossary now; summaries, the translation ledger and spend in later steps. Every
public method is one transaction. Each write to the glossary bumps `revision`,
which pages and staleness checks use as a cache key.

Concurrency: WAL with a 5 s busy timeout, so quick edits from the web can land
while a job runs; each thread uses its own connection.
"""

from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Self

import sqlalchemy as sa

from novel_translate.glossary import (
    AddAlias,
    AddTerm,
    Category,
    Edit,
    GlossaryError,
    RemoveAlias,
    Status,
    Term,
    UpdateTerm,
    normalize,
)
from novel_translate.matching import Matcher

SCHEMA_VERSION = 1
DB_NAME = "translate.sqlite"

type Clock = Callable[[], datetime]

_md = sa.MetaData()
_meta = sa.Table(
    "meta", _md,
    sa.Column("key", sa.String, primary_key=True),
    sa.Column("value", sa.String, nullable=False),
)  # fmt: skip
_term = sa.Table(
    "term", _md,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("zh", sa.String, nullable=False, unique=True),
    sa.Column("en", sa.String, nullable=False),
    sa.Column("category", sa.String, nullable=False),
    sa.Column("status", sa.String, nullable=False),
    sa.Column("gender", sa.String),
    sa.Column("notes", sa.String, nullable=False),
    sa.Column("origin", sa.String, nullable=False),
    sa.Column("confidence", sa.Float),
    sa.Column("first_chapter", sa.Integer),
    sa.Column("occurrences", sa.Integer, nullable=False),
    sa.Column("updated_at", sa.String, nullable=False),
    sa.Column("edited_at", sa.String),  # set by any user edit, never cleared
)  # fmt: skip
_alias = sa.Table(
    "alias", _md,
    sa.Column("zh", sa.String, primary_key=True),
    sa.Column("term_id", sa.ForeignKey("term.id", ondelete="CASCADE"), nullable=False),
)  # fmt: skip
_candidate = sa.Table(
    "candidate", _md,
    sa.Column("term_id", sa.ForeignKey("term.id", ondelete="CASCADE"), primary_key=True),
    sa.Column("en", sa.String, primary_key=True),
    sa.Column("origin", sa.String, primary_key=True),  # llm | official-en | mtl-glossary | side-channel
    sa.Column("votes", sa.Integer, nullable=False),
    sa.Column("examples_json", sa.String, nullable=False),
)  # fmt: skip


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


class TranslateStore:
    def __init__(self, engine: sa.Engine, clock: Clock):
        self._engine = engine
        self._clock = clock

    # -- lifecycle ---------------------------------------------------------

    @classmethod
    def create(cls, novel_dir: Path, clock: Clock = _utc_now) -> Self:
        db = novel_dir / DB_NAME
        if db.exists():
            raise FileExistsError(db)
        novel_dir.mkdir(parents=True, exist_ok=True)
        engine = _engine(db)
        with engine.begin() as conn:
            _md.create_all(conn)
            conn.exec_driver_sql(f"PRAGMA user_version={SCHEMA_VERSION}")
            conn.execute(_meta.insert().values(key="revision", value="0"))
        return cls(engine, clock)

    @classmethod
    def open(cls, novel_dir: Path, clock: Clock = _utc_now) -> Self:
        db = novel_dir / DB_NAME
        if not db.exists():
            raise FileNotFoundError(db)
        engine = _engine(db)
        with engine.connect() as conn:
            version = conn.exec_driver_sql("PRAGMA user_version").scalar()
        if version != SCHEMA_VERSION:
            engine.dispose()
            raise GlossaryError(f"{db}: schema version {version}, expected {SCHEMA_VERSION}")
        return cls(engine, clock)

    @classmethod
    def open_or_create(cls, novel_dir: Path, clock: Clock = _utc_now) -> Self:
        if (novel_dir / DB_NAME).exists():
            return cls.open(novel_dir, clock)
        return cls.create(novel_dir, clock)

    def close(self) -> None:
        self._engine.dispose()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- glossary ----------------------------------------------------------

    @property
    def revision(self) -> int:
        with self._engine.connect() as conn:
            return _revision(conn)

    def entries(
        self, status: Status | None = None, category: Category | None = None, search: str | None = None
    ) -> tuple[Term, ...]:
        """Terms in the order they were added; `search` matches zh (either script), aliases or en (any case)."""
        with self._engine.connect() as conn:
            terms = _load_terms(conn)
        if status is not None:
            terms = [t for t in terms if t.status is status]
        if category is not None:
            terms = [t for t in terms if t.category is category]
        if search:
            zh, en = normalize(search), search.casefold()
            terms = [t for t in terms if zh in t.zh or any(zh in a for a in t.aliases) or en in t.en.casefold()]
        return tuple(terms)

    def matcher(self) -> Matcher:
        return Matcher(self.entries())

    def apply(self, edits: Sequence[Edit]) -> int:
        """Apply the user's edits together, or none of them; returns the new revision."""
        now = self._now()
        with self._engine.begin() as conn:
            for edit in edits:
                match edit:
                    case AddTerm():
                        _add_term(conn, edit, now)
                    case UpdateTerm():
                        _update_term(conn, edit, now)
                    case AddAlias(term_id, zh):
                        _require_term(conn, term_id)
                        _add_alias(conn, term_id, zh)
                        _touch(conn, term_id, now)
                    case RemoveAlias(zh):
                        term_id = conn.execute(sa.select(_alias.c.term_id).where(_alias.c.zh == normalize(zh))).scalar()
                        if term_id is None:
                            raise GlossaryError(f"no alias {zh}")
                        conn.execute(_alias.delete().where(_alias.c.zh == normalize(zh)))
                        _touch(conn, term_id, now)
            return _bump(conn)

    def _now(self) -> str:
        return self._clock().isoformat()


def _revision(conn: sa.Connection) -> int:
    return int(conn.execute(sa.select(_meta.c.value).where(_meta.c.key == "revision")).scalar_one())


def _bump(conn: sa.Connection) -> int:
    revision = _revision(conn) + 1
    conn.execute(_meta.update().where(_meta.c.key == "revision").values(value=str(revision)))
    return revision


def _require_term(conn: sa.Connection, term_id: int) -> None:
    if conn.execute(sa.select(_term.c.id).where(_term.c.id == term_id)).scalar() is None:
        raise GlossaryError(f"no term {term_id}")


def _require_free(conn: sa.Connection, zh: str) -> None:
    """A key is used once, as a term's name or as an alias."""
    taken = conn.execute(sa.select(_term.c.id).where(_term.c.zh == zh)).scalar()
    if taken is None:
        taken = conn.execute(sa.select(_alias.c.term_id).where(_alias.c.zh == zh)).scalar()
    if taken is not None:
        raise GlossaryError(f"{zh} is already in the glossary (term {taken})")


def _add_term(conn: sa.Connection, edit: AddTerm, now: str) -> None:
    zh = normalize(edit.zh.strip())
    if not zh or not edit.en.strip():
        raise GlossaryError("a term needs both its Chinese and its English")
    _require_free(conn, zh)
    term_id = conn.execute(
        _term.insert().values(
            zh=zh, en=edit.en.strip(), category=str(edit.category), status=str(edit.status), gender=edit.gender or None,
            notes=edit.notes, origin="manual", occurrences=0, updated_at=now, edited_at=now,
        )
    ).inserted_primary_key[0]  # fmt: skip
    for alias in edit.aliases:
        _add_alias(conn, term_id, alias)


def _add_alias(conn: sa.Connection, term_id: int, zh: str) -> None:
    zh = normalize(zh.strip())
    _require_free(conn, zh)
    conn.execute(_alias.insert().values(zh=zh, term_id=term_id))


def _update_term(conn: sa.Connection, edit: UpdateTerm, now: str) -> None:
    _require_term(conn, edit.term_id)
    values: dict[str, object] = {}
    if edit.en is not None:
        if not edit.en.strip():
            raise GlossaryError("the English rendering cannot be empty")
        values["en"] = edit.en.strip()
    if edit.category is not None:
        values["category"] = str(edit.category)
    if edit.status is not None:
        values["status"] = str(edit.status)
    if edit.gender is not None:
        values["gender"] = edit.gender or None
    if edit.notes is not None:
        values["notes"] = edit.notes
    conn.execute(_term.update().where(_term.c.id == edit.term_id).values(**values, updated_at=now, edited_at=now))


def _touch(conn: sa.Connection, term_id: int, now: str) -> None:
    conn.execute(_term.update().where(_term.c.id == term_id).values(updated_at=now, edited_at=now))


def _load_terms(conn: sa.Connection) -> list[Term]:
    aliases: dict[int, list[str]] = defaultdict(list)
    for r in conn.execute(sa.select(_alias).order_by(_alias.c.zh)):
        aliases[r.term_id].append(r.zh)
    return [
        Term(
            r.id, r.zh, r.en, Category(r.category), Status(r.status), gender=r.gender, notes=r.notes,
            aliases=tuple(aliases[r.id]), origin=r.origin, edited=r.edited_at is not None,
            first_chapter=r.first_chapter, occurrences=r.occurrences,
        )
        for r in conn.execute(sa.select(_term).order_by(_term.c.id))
    ]  # fmt: skip
