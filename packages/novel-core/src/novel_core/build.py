"""Incremental build planning: which outputs are stale and which are orphaned."""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from novel_core.keys import ChapterKey, ItemRef, KeyRange
from novel_core.selection import Selected, SourceId


class OutputKind(StrEnum):
    SITE = "site"
    EPUB = "epub"
    AUDIO = "audio"


@dataclass(frozen=True)
class OutputRow:
    """A built artifact. There is one row per (kind, built_key)."""

    kind: OutputKind
    built_key: ChapterKey
    source_id: SourceId
    item_ref: ItemRef
    version_hash: str
    fingerprint: str
    artifact: str
    legacy: bool = False


@dataclass(frozen=True)
class VolumeRow:
    """A built volume (an M4B of the audio chapters numbered within `range`).

    `membership_hash` identifies the chapter audio it was built from; a different
    hash for the same range means the volume is stale.
    """

    range: KeyRange
    membership_hash: str
    artifact: str


@dataclass(frozen=True)
class BuildPlan:
    to_build: tuple[Selected, ...]
    to_prune: tuple[OutputRow, ...]


def plan_build(
    selection: Sequence[Selected],
    rows: Sequence[OutputRow],
    fingerprint: str,
    force: KeyRange | None = None,
) -> BuildPlan:
    """Build what changed (source, item, version or builder fingerprint); prune keys no longer selected.

    Legacy rows are never rebuilt or pruned, and an item that a legacy row already
    covers at another key is not built again; only `force` overrides both.
    """
    by_key = {r.built_key: r for r in rows}
    legacy_items = {(r.source_id, r.item_ref) for r in rows if r.legacy}
    forced = force.__contains__ if force else lambda _n: False

    to_build = []
    for s in selection:
        row = by_key.get(s.key)
        if forced(s.key.number):
            to_build.append(s)
        elif (row is not None and row.legacy) or (s.source_id, s.item_ref) in legacy_items:
            continue
        elif row is None or (row.source_id, row.item_ref, row.version_hash, row.fingerprint) != (
            s.source_id,
            s.item_ref,
            s.content_hash,
            fingerprint,
        ):
            to_build.append(s)

    selected_keys = {s.key for s in selection}
    to_prune = [
        r
        for r in rows
        if r.built_key not in selected_keys and (not r.legacy or forced(r.built_key.number))
    ]
    return BuildPlan(tuple(to_build), tuple(sorted(to_prune, key=lambda r: r.built_key)))
