"""Reclean: run today's zh rules again over a raw-zh source's stored chapters, from the kept raws.

Nothing is fetched. A text raw is cleaned and checked again from the kept page (so a new or
changed cleaner rewrites it); an HTML raw, or a chapter stored without its raw, keeps its
blocks and is only checked again. Each result goes through put_version: identical text is
Unchanged and only takes the new findings and rules_rev, so a reclean that changes nothing
leaves every chapter current as it was. Old versions are never deleted.
"""

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass

from novel_core import Finding, Inserted, ItemRef, NovelStore, SourceId

from novel_sources.clean import CleanRules
from novel_sources.zh_rules import ZhRules


@dataclass(frozen=True)
class RecleanReport:
    source_id: SourceId
    chapters: int  # current versions rechecked
    rewritten: int  # their text changed: a new version is current
    unchanged: int
    hits: Mapping[str, int]  # lines each cleaner changed, by cleaner name, in rule order
    held: tuple[tuple[ItemRef, tuple[Finding, ...]], ...]  # held now and not before, with the findings
    cleared: tuple[ItemRef, ...]  # held before and not now


def reclean(store: NovelStore, source_id: SourceId, zh: ZhRules) -> RecleanReport:
    """Clean and check every mapped item's current version of this source again with `zh`."""
    current = store.view().chapters(source_id)
    refs = [s.item_ref for s in current]
    held_before = store.view().held_items(source_id, refs)
    hits: Counter[str] = Counter({c.name: 0 for c in zh.cleaners})
    rewritten = 0
    for s in current:
        v = store.read_version(s.version_id)
        raw = store.read_raw(s.version_id)
        if raw is not None and raw.content_type == "text":
            hits.update(h.rule for h in zh.trace(raw.content))
            new = zh.version(raw, v.title, CleanRules(content=()), v.provenance)
        else:
            new = zh.recheck(v)
        rewritten += isinstance(store.put_version(source_id, s.item_ref, new), Inserted)
    held_after = store.view().held_items(source_id, refs)
    return RecleanReport(
        source_id, len(current), rewritten, len(current) - rewritten,
        {name: n for name, n in hits.items() if n},
        tuple((ref, found) for ref, found in held_after.items() if ref not in held_before),
        tuple(ref for ref in held_before if ref not in held_after),
    )  # fmt: skip
