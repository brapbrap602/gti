"""TranslateStore: the single owner of one novel's `translate.sqlite`.

It sits beside `novel.sqlite` and holds what translation adds to a novel: the
glossary now; summaries, the translation ledger and spend in later steps. Every
public method is one transaction. Each write to the glossary bumps `revision`,
which pages and staleness checks use as a cache key.

Concurrency: WAL with a 5 s busy timeout, so quick edits from the web can land
while a job runs; each thread uses its own connection.
"""

import json
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Self

import sqlalchemy as sa

from novel_translate.glossary import (
    AddAlias,
    AddTerm,
    Candidate,
    Category,
    Edit,
    GlossaryError,
    RemoveAlias,
    Seen,
    Status,
    Term,
    UpdateTerm,
    Verdict,
    normalize,
    resolve,
)
from novel_translate.matching import Matcher

SCHEMA_VERSION = 1
DB_NAME = "translate.sqlite"

type Clock = Callable[[], datetime]
type Key = tuple[int, int]  # chapter (number, part)


@dataclass(frozen=True)
class StoredSummary:
    raw_hash: str
    model: str
    text: str

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
    sa.Column("snippets_json", sa.String, nullable=False, server_default="[]"),
    sa.Column("updated_at", sa.String, nullable=False),
    sa.Column("edited_at", sa.String),  # set by any user edit, never cleared
    sa.Column("hinted_at", sa.String),  # official English was consulted for it
    sa.Column("consulted_json", sa.String, nullable=False, server_default="[]"),  # chapters asked so far
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
_summary = sa.Table(
    "summary", _md,
    sa.Column("number", sa.Integer, primary_key=True),
    sa.Column("part", sa.Integer, primary_key=True),
    sa.Column("raw_hash", sa.String, nullable=False),
    sa.Column("model", sa.String, nullable=False),
    sa.Column("text", sa.String, nullable=False),
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

    def candidates(self, term_id: int) -> tuple[Candidate, ...]:
        """The evidence for a term: renderings by origin, most voted first."""
        with self._engine.connect() as conn:
            rows = conn.execute(sa.select(_candidate).where(_candidate.c.term_id == term_id))
            return tuple(sorted((Candidate(r.en, r.votes, r.origin) for r in rows), key=lambda c: (-c.votes, c.en)))

    def counts(self) -> dict[Status, int]:
        """How many terms have each status (statuses with none left out)."""
        with self._engine.connect() as conn:
            rows = conn.execute(sa.select(_term.c.status, sa.func.count()).group_by(_term.c.status))
            return {Status(status): n for status, n in rows}

    def evidence(self, term_ids: Sequence[int]) -> dict[int, tuple[tuple[Candidate, ...], tuple[str, ...]]]:
        """For each term: its candidates (most voted first) and the raw snippets it was seen in."""
        with self._engine.connect() as conn:
            candidates = _load_candidates(conn, term_ids)
            rows = conn.execute(sa.select(_term.c.id, _term.c.snippets_json).where(_term.c.id.in_(term_ids)))
            snippets = {r.id: tuple(json.loads(r.snippets_json)) for r in rows}
        ranked = {t: tuple(sorted(cs, key=lambda c: (-c.votes, c.en))) for t, cs in candidates.items()}
        return {t: (ranked.get(t, ()), snippets.get(t, ())) for t in term_ids}

    def snippets(self, term_id: int) -> tuple[str, ...]:
        with self._engine.connect() as conn:
            raw = conn.execute(sa.select(_term.c.snippets_json).where(_term.c.id == term_id)).scalar()
            return tuple(json.loads(raw or "[]"))

    # -- glossary pass writes (never over a user's edit) -------------------

    def known_keys(self) -> frozenset[str]:
        """Every name and alias, whatever its status: discovery never proposes them again."""
        with self._engine.connect() as conn:
            names = conn.execute(sa.select(_term.c.zh)).scalars().all()
            aliases = conn.execute(sa.select(_alias.c.zh)).scalars().all()
            return frozenset([*names, *aliases])

    def record_verdicts(self, verdicts: Sequence[Verdict], seen: Mapping[str, Seen]) -> None:
        """Store the model's verdicts: new terms, or evidence for existing ones.

        A new term is `proposed` until `resolve`, or `rejected` if the model says it is
        no term. An existing term gets the votes as candidates; its category, gender and
        status change only if the user never edited it.
        """
        now = self._now()
        with self._engine.begin() as conn:
            for v in verdicts:
                zh = normalize(v.zh)
                status = Status.PROPOSED if v.is_term else Status.REJECTED
                facts = {}
                if where := seen.get(zh):
                    facts = {
                        "first_chapter": where.first_chapter,
                        "occurrences": where.occurrences,
                        "snippets_json": json.dumps(list(where.snippets), ensure_ascii=False),
                    }
                term_id = conn.execute(sa.select(_term.c.id).where(_term.c.zh == zh)).scalar()
                if term_id is None:
                    term_id = conn.execute(
                        _term.insert().values(
                            zh=zh, en=_top(v.renderings) or zh, category=str(v.category), status=str(status),
                            gender=v.gender, notes="", origin="discovered", updated_at=now, **({"occurrences": 0} | facts),
                        )
                    ).inserted_primary_key[0]  # fmt: skip
                else:
                    if facts:
                        conn.execute(_term.update().where(_term.c.id == term_id).values(**facts))
                    conn.execute(
                        _term.update()
                        .where(_term.c.id == term_id, _term.c.edited_at.is_(None))
                        .values(category=str(v.category), gender=v.gender, status=str(status), updated_at=now)
                    )
                _add_votes(conn, term_id, "llm", v.renderings)
                for alias in v.aliases:
                    alias = normalize(alias.strip())
                    if alias and _taken(conn, alias) is None:
                        conn.execute(_alias.insert().values(zh=alias, term_id=term_id))
            _bump(conn)

    def propose(self, terms: Sequence[tuple[str, str, Category]]) -> int:
        """New terms a translation reported (zh, en, category): `proposed`, never injected or blocking,
        until a glossary pass scores them. Names already in the glossary, rejected ones included,
        are ignored. Returns how many were added."""
        now = self._now()
        added = 0
        with self._engine.begin() as conn:
            for zh, en, category in terms:
                zh, en = normalize(zh.strip()), en.strip()
                if not zh or not en or _taken(conn, zh) is not None:
                    continue
                term_id = conn.execute(
                    _term.insert().values(
                        zh=zh, en=en, category=str(category), status=str(Status.PROPOSED), notes="",
                        origin="side-channel", occurrences=0, updated_at=now,
                    )
                ).inserted_primary_key[0]  # fmt: skip
                _add_votes(conn, term_id, "side-channel", [en])
                added += 1
            if added:
                _bump(conn)
        return added

    def unhinted(self) -> tuple[Term, ...]:
        """Terms official English has not been consulted for yet (never rejected ones)."""
        with self._engine.connect() as conn:
            ids = set(
                conn.execute(
                    sa.select(_term.c.id).where(_term.c.hinted_at.is_(None), _term.c.status != str(Status.REJECTED))
                ).scalars()
            )
            return tuple(t for t in _load_terms(conn) if t.id in ids)

    def consulted(self) -> dict[int, set[int]]:
        """Per term not yet hinted, the chapters whose official English was already asked about it."""
        with self._engine.connect() as conn:
            rows = conn.execute(sa.select(_term.c.id, _term.c.consulted_json).where(_term.c.hinted_at.is_(None)))
            return {r.id: set(json.loads(r.consulted_json)) for r in rows}

    def record_hints(
        self, renderings: Mapping[int, Sequence[str]], consulted: Mapping[int, int], done: Iterable[int]
    ) -> None:
        """Official English renderings become candidates; `consulted` maps terms to the chapter asked;
        the `done` terms are marked hinted."""
        now = self._now()
        with self._engine.begin() as conn:
            for term_id, ens in renderings.items():
                _add_votes(conn, term_id, "official-en", ens)
            for term_id, number in consulted.items():
                raw = conn.execute(sa.select(_term.c.consulted_json).where(_term.c.id == term_id)).scalar_one()
                chapters = sorted(set(json.loads(raw)) | {number})
                conn.execute(_term.update().where(_term.c.id == term_id).values(consulted_json=json.dumps(chapters)))
            if done := list(done):
                conn.execute(_term.update().where(_term.c.id.in_(done)).values(hinted_at=now))
            _bump(conn)

    def resolve(self, revote: bool = False) -> dict[Status, int]:
        """Decide unedited proposed and needs-review terms (accepted ones too with `revote`) from their votes."""
        open_statuses = [Status.PROPOSED, Status.NEEDS_REVIEW] + ([Status.ACCEPTED] if revote else [])
        now = self._now()
        decided_counts: dict[Status, int] = defaultdict(int)
        with self._engine.begin() as conn:
            term_ids = conn.execute(
                sa.select(_term.c.id).where(
                    _term.c.edited_at.is_(None), _term.c.status.in_([str(s) for s in open_statuses])
                )
            ).scalars().all()  # fmt: skip
            votes = _load_candidates(conn)
            for term_id in term_ids:
                decided = resolve(votes.get(term_id, ()))
                if decided is None:
                    continue
                conn.execute(
                    _term.update()
                    .where(_term.c.id == term_id, _term.c.edited_at.is_(None))
                    .values(status=str(decided.status), en=decided.en, confidence=decided.confidence, updated_at=now)
                )
                decided_counts[decided.status] += 1
            _bump(conn)
        return dict(decided_counts)

    # -- summaries and the discovery cache ----------------------------------

    def summaries(self) -> dict[Key, StoredSummary]:
        with self._engine.connect() as conn:
            rows = conn.execute(sa.select(_summary))
            return {(r.number, r.part): StoredSummary(r.raw_hash, r.model, r.text) for r in rows}

    def put_summary(self, key: Key, raw_hash: str, model: str, text: str) -> None:
        number, part = key
        with self._engine.begin() as conn:
            conn.execute(_summary.delete().where(_summary.c.number == number, _summary.c.part == part))
            conn.execute(_summary.insert().values(number=number, part=part, raw_hash=raw_hash, model=model, text=text))

    def discovery(self, raws_hash: str) -> list[tuple[str, int]] | None:
        """The candidates found in exactly these raws, if discovery already ran over them."""
        with self._engine.connect() as conn:
            raw = conn.execute(sa.select(_meta.c.value).where(_meta.c.key == "discovery")).scalar()
        if raw is None:
            return None
        cached = json.loads(raw)
        return [(zh, count) for zh, count in cached["candidates"]] if cached["raws"] == raws_hash else None

    def set_discovery(self, raws_hash: str, candidates: Sequence[tuple[str, int]]) -> None:
        value = json.dumps({"raws": raws_hash, "candidates": [list(c) for c in candidates]}, ensure_ascii=False)
        with self._engine.begin() as conn:
            conn.execute(_meta.delete().where(_meta.c.key == "discovery"))
            conn.execute(_meta.insert().values(key="discovery", value=value))

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


def _taken(conn: sa.Connection, zh: str) -> int | None:
    """The term that uses this key, as its name or as an alias."""
    taken = conn.execute(sa.select(_term.c.id).where(_term.c.zh == zh)).scalar()
    if taken is None:
        taken = conn.execute(sa.select(_alias.c.term_id).where(_alias.c.zh == zh)).scalar()
    return taken


def _require_free(conn: sa.Connection, zh: str) -> None:
    """A key is used once, as a term's name or as an alias."""
    if (taken := _taken(conn, zh)) is not None:
        raise GlossaryError(f"{zh} is already in the glossary (term {taken})")


def _add_votes(conn: sa.Connection, term_id: int, origin: str, renderings: Iterable[str]) -> None:
    for en in renderings:
        if not (en := en.strip()):
            continue
        key = (_candidate.c.term_id == term_id, _candidate.c.en == en, _candidate.c.origin == origin)
        if conn.execute(_candidate.update().where(*key).values(votes=_candidate.c.votes + 1)).rowcount == 0:
            conn.execute(_candidate.insert().values(term_id=term_id, en=en, origin=origin, votes=1, examples_json="[]"))


def _load_candidates(conn: sa.Connection, term_ids: Sequence[int] | None = None) -> dict[int, list[Candidate]]:
    out: dict[int, list[Candidate]] = defaultdict(list)
    query = sa.select(_candidate) if term_ids is None else sa.select(_candidate).where(_candidate.c.term_id.in_(term_ids))
    for r in conn.execute(query):
        out[r.term_id].append(Candidate(r.en, r.votes, r.origin))
    return out


def _top(renderings: Sequence[str]) -> str | None:
    counts: dict[str, int] = defaultdict(int)
    for en in renderings:
        if en.strip():
            counts[en.strip()] += 1
    return max(counts, key=lambda en: (counts[en], en)) if counts else None


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
