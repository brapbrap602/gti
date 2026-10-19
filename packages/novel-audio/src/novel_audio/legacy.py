"""Register the old tts_reader output (`<dir>/chapter_NNN/chapter_NNN.mp3`) as built audio.

Each folder number NNN is mapped to an item of one source:
- `Positions`: NNN is a position in a frozen chapter list (the WNS import
  snapshot), counted from 1. The Calibre exports tts_reader read did not
  always list exactly the same posts, so `shifts` move ranges of folders:
  `Shift(KeyRange(736, 1442), 4)` maps folder 736 to position 740.
- `TitleNumbers`: NNN is the chapter number; the item deriving to key NNN is used.

Every mapping is checked before it is registered. tts_reader kept one MP3 per
sentence (`chNNN_pPPP_sSSS.mp3`), and a paragraph's summed MP3 size follows
its length in characters. So a folder records the shape of its text: the
sequence of paragraph lengths. That shape is compared with each candidate
version's paragraph lengths in two ways (a lag-tolerant correlation, and a
diff of coarse length buckets that survives paragraphs inserted or dropped by
later cleanup). A mapping is accepted when its version beats every other
version within SEARCH positions or numbers on at least one of them; reposts
with identical text are not counted as rivals. On the real BTS, CCG,
Barbarian and WLHC folders this accepted 600 of 600 sampled true mappings and
1 of 593 deliberately wrong ones. A rejected mapping is reported with the
position or number that matched best, which is how a needed shift shows up.
Folders without sentence files, or with under MIN_PARAGRAPHS paragraphs, carry
too little shape to check and are registered as unverified.

Registered rows are legacy outputs: built_key is the item's derived key, the
artifact is the MP3's absolute path, and builds never rebuild or delete them
unless forced. Only folders with a non-empty combined MP3 are registered.
"""

import math
import re
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from novel_core import ChapterKey, ItemRef, KeyRange, NovelStore, OutputKind, Selected, SourceId

from novel_audio.script import spoken_texts

LEGACY_FINGERPRINT = "legacy"
SEARCH = 30  # rivals: every version mapped within this many positions or numbers
MIN_PARAGRAPHS = 3
MAX_LAG = 4  # paragraphs the correlation may slide to absorb a few added or dropped at the start

_FOLDER = re.compile(r"chapter_(\d+)$")
_SENTENCE = re.compile(r"ch\d+_p(\d+)_s\d+\.mp3$")

type Shape = list[float]  # log length of each paragraph


@dataclass(frozen=True)
class Positions:
    refs: Sequence[ItemRef]  # refs[0] is position 1


@dataclass(frozen=True)
class TitleNumbers:
    pass


type LegacyKeys = Positions | TitleNumbers


@dataclass(frozen=True)
class Shift:
    folders: KeyRange
    by: int


@dataclass(frozen=True)
class Mismatch:
    folder: int
    key: ChapterKey  # what the folder was mapped to
    best: int  # the position or number whose text matched the folder better


@dataclass(frozen=True)
class LegacyReport:
    registered: tuple[tuple[int, ChapterKey], ...]
    unverified: tuple[int, ...]  # registered without enough shape to check against
    partial: tuple[int, ...]  # no combined MP3: left for the builder
    unmapped: tuple[tuple[int, str], ...]  # (folder, why)
    mismatched: tuple[Mismatch, ...]
    already_built: tuple[int, ...]  # the key has newly built audio, which wins


def register_legacy(
    store: NovelStore,
    folder: Path,
    source: SourceId,
    keys: LegacyKeys,
    shifts: Sequence[Shift] = (),
) -> LegacyReport:
    chapters = store.chapters(source)
    by_ref = {c.item_ref: c for c in chapters}
    by_number = {c.key.number: c for c in chapters if c.key.part == 0}
    built = {r.built_key for r in store.outputs(OutputKind.AUDIO) if not r.legacy}
    shapes = _Shapes(store)

    def target(n: int) -> Selected | None:
        if isinstance(keys, TitleNumbers):
            return by_number.get(n)
        return by_ref.get(keys.refs[n - 1]) if 1 <= n <= len(keys.refs) else None

    registered, unverified, partial, unmapped, mismatched, already_built = [], [], [], [], [], []
    for number, path in _folders(folder):
        mp3 = path / f"{path.name}.mp3"
        if not mp3.is_file() or mp3.stat().st_size == 0:
            partial.append(number)
            continue
        n = number + next((s.by for s in shifts if number in s.folders), 0)
        chapter = target(n)
        if chapter is None:
            what = "position" if isinstance(keys, Positions) else "chapter"
            unmapped.append((number, f"{what} {n} has no item with a key"))
            continue
        if chapter.key in built:
            already_built.append(number)
            continue
        legacy = _legacy_shape(path)
        if len(legacy) < MIN_PARAGRAPHS:
            unverified.append(number)
        else:
            rivals = {
                m: c for m in range(n - SEARCH, n + SEARCH + 1)
                if m != n and (c := target(m)) is not None and c.content_hash != chapter.content_hash
            }  # fmt: skip
            if not _beats_all(legacy, shapes.of(chapter), [shapes.of(c) for c in rivals.values()]):
                best = max(rivals, key=lambda m: _lagged_correlation(legacy, shapes.of(rivals[m])))
                mismatched.append(Mismatch(number, chapter.key, best))
                continue
        store.record_output(OutputKind.AUDIO, chapter, LEGACY_FINGERPRINT, str(mp3.resolve()), legacy=True)
        registered.append((number, chapter.key))
    return LegacyReport(*map(tuple, (registered, unverified, partial, unmapped, mismatched, already_built)))


def _folders(folder: Path) -> list[tuple[int, Path]]:
    found = [(int(m.group(1)), d) for d in folder.iterdir() if d.is_dir() and (m := _FOLDER.match(d.name))]
    return sorted(found)


def _legacy_shape(folder: Path) -> Shape:
    """Log of each paragraph's summed sentence-MP3 size (p000, the title, is left out)."""
    sizes: dict[int, int] = defaultdict(int)
    for f in folder.iterdir():
        if (m := _SENTENCE.match(f.name)) and int(m.group(1)):
            sizes[int(m.group(1))] += f.stat().st_size
    return _logs(sizes[p] for p in range(1, max(sizes, default=0) + 1))


def _logs(lengths) -> Shape:
    return [math.log(x) for x in lengths if x > 0]


def _beats_all(legacy: Shape, mapped: Shape, rivals: Sequence[Shape]) -> bool:
    def wins(score: Callable[[Shape, Shape], float]) -> bool:
        mine = score(legacy, mapped)
        return all(mine > score(legacy, r) for r in rivals)

    return wins(_lagged_correlation) or wins(_bucket_match)


def _lagged_correlation(a: Shape, b: Shape) -> float:
    return max(_correlation(a[k:], b) if k >= 0 else _correlation(a, b[-k:]) for k in range(-MAX_LAG, MAX_LAG + 1))


def _correlation(a: Shape, b: Shape) -> float:
    n = min(len(a), len(b))
    if n < MIN_PARAGRAPHS:
        return 0.0
    a, b = a[:n], b[:n]
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va == 0 or vb == 0:
        return 0.0
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(va * vb)


def _bucket_match(a: Shape, b: Shape) -> float:
    """Diff ratio of lengths in half-octave steps around each text's mean, so scale doesn't matter."""
    return SequenceMatcher(None, _buckets(a), _buckets(b), autojunk=False).ratio()


def _buckets(shape: Shape) -> list[int]:
    if not shape:
        return []
    mean = sum(shape) / len(shape)
    return [round(2 * (x - mean) / math.log(2)) for x in shape]


class _Shapes:
    """Paragraph-length shapes of versions, read once each."""

    def __init__(self, store: NovelStore):
        self._store = store
        self._seen: dict[int, Shape] = {}

    def of(self, chapter: Selected) -> Shape:
        if chapter.version_id not in self._seen:
            blocks = self._store.read_version(chapter.version_id).blocks
            self._seen[chapter.version_id] = _logs(len(text) for text in spoken_texts(blocks))
        return self._seen[chapter.version_id]
