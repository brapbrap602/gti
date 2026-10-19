"""M4B volumes: the chapter audio of each range of `size` chapter numbers as one audiobook file.

A volume holds every selected chapter in its range that has audio (built or
legacy), in key order, with a chapter mark per chapter. Its membership hash
covers each member's key, text hash, fingerprint and file, so a volume is
rebuilt exactly when one of its chapters changed, appeared or went away.
A volume left with no chapters is deleted.
"""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from novel_core import KeyRange, NovelStore, OutputKind, OutputRow, VolumeRow, chapter_heading

from novel_audio.media import Marker, Tags, duration_ms, encode_m4b

VOLUMES = "volumes"
VOLUME_SIZE = 100

type VolumeProgress = Callable[[KeyRange, int, int], None]  # (range, index from 1, total)


@dataclass(frozen=True)
class VolumeReport:
    built: tuple[KeyRange, ...]
    pruned: tuple[KeyRange, ...]
    incomplete: tuple[tuple[KeyRange, int], ...]  # built volumes missing this many selected chapters


def build_volumes(
    store: NovelStore,
    out_dir: Path,
    *,
    size: int = VOLUME_SIZE,
    cover: bytes | None = None,
    progress: VolumeProgress | None = None,
) -> VolumeReport:
    meta = store.meta
    selection = {s.key: s for s in store.selection()}
    audio = [r for r in store.outputs(OutputKind.AUDIO) if r.built_key in selection]

    members: dict[KeyRange, list[OutputRow]] = {}
    for row in audio:
        members.setdefault(KeyRange.containing(row.built_key.number, size), []).append(row)
    wanted: dict[KeyRange, int] = {}
    for key in selection:
        r = KeyRange.containing(key.number, size)
        wanted[r] = wanted.get(r, 0) + 1
    existing = {v.range: v for v in store.volumes()}

    todo = []
    for r, rows in sorted(members.items(), key=lambda kv: kv[0].start):
        digest = _membership_hash(rows)
        old = existing.get(r)
        if old is None or old.membership_hash != digest or not (out_dir / old.artifact).exists():
            todo.append((r, rows, digest))

    for i, (r, rows, digest) in enumerate(todo, start=1):
        if progress:
            progress(r, i, len(todo))
        markers, start = [], 0
        for row in rows:
            length = duration_ms(out_dir / row.artifact)
            title = chapter_heading(row.built_key, selection[row.built_key].title)
            markers.append(Marker(title, start, start + length))
            start += length
        name = f"{VOLUMES}/{r.start:04d}-{r.end:04d}.m4b"
        label = f"{rows[0].built_key.label}–{rows[-1].built_key.label}"
        tags = Tags(f"{meta.title} {label}", meta.title, meta.author, cover=cover)
        encode_m4b([out_dir / row.artifact for row in rows], markers, out_dir / name, tags)
        store.record_volume(VolumeRow(r, digest, name))

    pruned = sorted((r for r in existing if r not in members), key=lambda r: r.start)
    for r in pruned:
        (out_dir / existing[r].artifact).unlink(missing_ok=True)
        store.prune_volume(r)

    incomplete = tuple(
        (r, wanted[r] - len(rows)) for r, rows, _ in todo if len(rows) < wanted.get(r, 0)
    )
    return VolumeReport(tuple(r for r, _, _ in todo), tuple(pruned), incomplete)


def _membership_hash(rows: list[OutputRow]) -> str:
    h = hashlib.sha256()
    for r in rows:
        h.update(f"{r.built_key.number}\0{r.built_key.part}\0{r.version_hash}\0{r.fingerprint}\0{r.artifact}\n".encode())
    return h.hexdigest()

