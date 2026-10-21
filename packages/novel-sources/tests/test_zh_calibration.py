"""Gate G1: today's zh rules over every stored raw-zh chapter of the real library flag exactly the known ones.

Local only: `pytest -m scale`, with NOVELS_DATA_DIR pointing at the library, or better a copy of it
(opening a store migrates it). Findings are computed in memory from the kept raws, as a reclean
would; nothing is written. Every mapped chapter is checked: what reclean, check and translation read.
"""

import os
from pathlib import Path

import pytest
from novel_core import NovelStore

from novel_sources.backends import site_key, zh_rules
from novel_sources.clean import CleanRules

# (slug, site key, chapter number, check). Poison: hand-confirmed scrambles (Longevity 651 is ref /50537/654).
# Decoy names: biquge5 chapters that keep the real opening, then drift off without the novel's people.
KNOWN = {
    ("in-the-name-of-divine-powers", "ixdzs8", 691, "poison"),
    ("in-the-name-of-divine-powers", "ixdzs8", 692, "poison"),
    ("in-the-name-of-divine-powers", "ixdzs8", 693, "poison"),
    ("my-longevity-simulation", "biquges123", 651, "poison"),
    ("in-the-name-of-divine-powers", "biquge5", 600, "decoy-names"),
    ("in-the-name-of-divine-powers", "biquge5", 694, "decoy-names"),
    ("in-the-name-of-divine-powers", "biquge5", 695, "decoy-names"),
    ("in-the-name-of-divine-powers", "biquge5", 696, "decoy-names"),
}


def library() -> Path:
    configured = os.environ.get("NOVELS_DATA_DIR")
    if not configured or not Path(configured).is_dir():
        pytest.skip("NOVELS_DATA_DIR is not set to a library")
    return Path(configured)


@pytest.mark.scale
def test_rules_flag_exactly_the_known_poisoned_and_decoy_chapters():
    flagged, checked = set(), 0
    for folder in sorted(library().iterdir()):
        if folder.name.startswith("_") or not (folder / "novel.sqlite").is_file():
            continue
        with NovelStore.open(folder) as store:
            view = store.view()
            for info in view.sources:
                if (zh := zh_rules(folder.name, info.spec)) is None:
                    continue
                for s in view.chapters(info.id):
                    v, raw = store.read_version(s.version_id), store.read_raw(s.version_id)
                    if raw is not None and raw.content_type == "text":
                        new = zh.version(raw, v.title, CleanRules(content=()), v.provenance)
                    else:
                        new = zh.recheck(v)
                    checked += 1
                    flagged |= {(folder.name, site_key(info.spec), s.key.number, f.check) for f in new.findings}
    print(f"\n{checked} raw-zh chapters checked")
    assert flagged == KNOWN
