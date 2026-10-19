"""Per-chapter MP3s for the selected chapters, built incrementally.

A chapter is (re)built when `NovelStore.plan_build` says so (new, changed or
re-selected text, or a new voice or script fingerprint) or when its file is
missing. Chapters are built one at a time and recorded as soon as each is
done, so an interrupted build resumes where it stopped; the sentence cache
keeps whatever was synthesized for the chapter in flight. Legacy chapters
(registered from the old tts_out folders) are never rebuilt unless forced,
and their files are never deleted.
"""

import asyncio
import hashlib
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from novel_core import ChapterKey, KeyRange, NovelMeta, NovelStore, OutputKind, Selected, chapter_heading

from novel_audio import script
from novel_audio.media import Tags, join_mp3, tag_mp3
from novel_audio.tts import SentenceCache, TtsEngine

SENTENCES = "_sentences"
EVERYTHING = KeyRange(0, 10**9)

type Progress = Callable[[Selected, int, int], None]  # (chapter, index from 1, total)


@dataclass(frozen=True)
class AudioReport:
    built: tuple[ChapterKey, ...]
    pruned: tuple[ChapterKey, ...]
    synthesized: int  # sentences sent to the TTS engine
    reused: int  # sentences found in the cache


def fingerprint(voice: str) -> str:
    """Changes when the voice or the way text is turned into sentences changes."""
    return hashlib.sha256(f"voice={voice}\n".encode() + Path(script.__file__).read_bytes()).hexdigest()


def chapter_file(key: ChapterKey) -> str:
    return f"chapter_{key.number:04d}-{key.part}.mp3" if key.part else f"chapter_{key.number:04d}.mp3"


def build_audio(
    store: NovelStore,
    out_dir: Path,
    tts: TtsEngine,
    *,
    keys: KeyRange | None = None,
    force: bool = False,
    cover: bytes | None = None,
    concurrency: int = 2,
    progress: Progress | None = None,
) -> AudioReport:
    """Build the stale chapters numbered within `keys` (all when None) into out_dir.

    `force` rebuilds every chapter in `keys`, legacy ones included. Chapters that
    are no longer selected are pruned whatever `keys` says.
    """
    return asyncio.run(_build(store, out_dir, tts, keys or EVERYTHING, force, cover, concurrency, progress))


async def _build(
    store: NovelStore,
    out_dir: Path,
    tts: TtsEngine,
    keys: KeyRange,
    force: bool,
    cover: bytes | None,
    concurrency: int,
    progress: Progress | None,
) -> AudioReport:
    fp = fingerprint(tts.voice)
    plan = store.plan_build(OutputKind.AUDIO, fp, force=keys if force else None)
    missing = {
        r.built_key for r in store.outputs(OutputKind.AUDIO) if not r.legacy and not (out_dir / r.artifact).exists()
    }
    planned = {s.key for s in plan.to_build}
    todo = [
        s for s in store.selection()
        if s.key.number in keys and (s.key in planned or s.key in missing)
    ]  # fmt: skip

    meta = store.meta
    cache = SentenceCache(out_dir / SENTENCES, tts)
    limit = asyncio.Semaphore(concurrency)
    for i, selected in enumerate(todo, start=1):
        if progress:
            progress(selected, i, len(todo))
        version = store.read_version(selected.version_id)
        lines = script.chapter_script(selected.key, version.title, version.blocks)
        parts = await cache.render(lines, limit)
        name = chapter_file(selected.key)
        join_mp3(parts, out_dir / name)
        tag_mp3(out_dir / name, _tags(meta, selected.key, version.title, cover))
        store.record_output(OutputKind.AUDIO, selected, fp, name)

    for row in plan.to_prune:
        if not row.legacy:
            _remove_inside(out_dir, row.artifact)
        store.prune_output(OutputKind.AUDIO, row.built_key)

    return AudioReport(
        tuple(s.key for s in todo), tuple(r.built_key for r in plan.to_prune), cache.synthesized, cache.reused
    )


def retag_audio(store: NovelStore, out_dir: Path, cover: bytes | None = None) -> int:
    """Rewrite the tags of every chapter MP3 that has audio, legacy ones included; returns how many."""
    meta = store.meta
    selection = {s.key: s for s in store.selection()}
    done = 0
    for row in store.outputs(OutputKind.AUDIO):
        path = out_dir / row.artifact
        if row.built_key in selection and path.exists():
            tag_mp3(path, _tags(meta, row.built_key, selection[row.built_key].title, cover))
            done += 1
    return done


def _tags(meta: NovelMeta, key: ChapterKey, title: str, cover: bytes | None) -> Tags:
    return Tags(chapter_heading(key, title), meta.title, meta.author, key.number, cover=cover)


def _remove_inside(folder: Path, artifact: str) -> None:
    """Delete a built file, but never anything outside the audio folder."""
    path = (folder / artifact).resolve()
    if path.is_relative_to(folder.resolve()) and path.exists():
        os.remove(path)
