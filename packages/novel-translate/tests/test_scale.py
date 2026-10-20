"""Discovery over all of Transcendental Mechanic (about 5M characters), on the real data dir.

Local only: `pytest -m scale`. Limits from the plan: under 5 minutes and 2 GB.
"""

import time
import tracemalloc

import pytest
from novel_core import Kind, NovelStore, Paragraph
from novel_translate.discover import candidates
from novel_translate.glossary import normalize

from novel_app.library import novel_dir


@pytest.mark.scale
def test_discovery_over_a_whole_long_novel_stays_within_time_and_memory():
    folder = novel_dir("transcendental-mechanic")
    if not (folder / "novel.sqlite").exists():
        pytest.skip("no Transcendental Mechanic in the data dir")
    with NovelStore.open(folder) as store:
        view = store.view()
        raws = [s for info in view.sources if info.spec.kind is Kind.RAW_ZH for s in view.chapters(info.id)]
        texts = [
            normalize("\n".join(b.text for b in store.read_version(s.version_id).blocks if isinstance(b, Paragraph)))
            for s in raws
        ]
    assert sum(map(len, texts)) > 4_000_000

    tracemalloc.start()
    started = time.monotonic()
    found = candidates(texts, known=set())
    elapsed, peak = time.monotonic() - started, tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()

    print(f"\n{len(found)} candidates in {elapsed:.0f} s, peak {peak / 2**20:.0f} MiB")
    assert elapsed < 300 and peak < 2 * 2**30
    assert found[0].zh == "韩萧"  # the protagonist
