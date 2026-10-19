import json

from novel_core import ChapterKey, NovelStore
from novel_sources.importing import import_novel
from novel_sources.wns import SNAPSHOT_NAME, WnsImporter

GOLDEN = "https://novelbin.me/novel-book/my-golden-core"
MOUNT_HUA = "https://skydemonorder.com/projects/3801994495-return-of-the-mount-hua-sect"


def golden_core(wns):
    """novelbin pages saved under hash names; numbers come from titles, extras have none."""
    folder = wns("My Golden Core", GOLDEN)
    for n in (1, 2, 3):
        folder.chapter(f"{GOLDEN}/chapter-{n}-name-{n}", f"Chapter {n}: Name {n}", f"my-golden-core_{n:08x}.html")
    folder.chapter(f"{GOLDEN}/extra-1-the-game", "Extra 1: The game has just begun", "my-golden-core_extra.html")
    return folder


def mount_hua(wns):
    """skydemonorder: titles carry no number, slugs do; 1-2 were never downloaded (locked)."""
    folder = wns("Return of the Mount Hua Sect", MOUNT_HUA)
    folder.chapter(f"{MOUNT_HUA}/1-what-the-hell-1", None, None)
    folder.chapter(f"{MOUNT_HUA}/2-what-the-hell-2", None, None)
    for n, arc in ((3, 1), (4, 2)):
        body = f'<div id="chapter-body"><p>What Is It? ({arc})</p><p>Body {n}.</p></div>'
        folder.chapter(f"{MOUNT_HUA}/{n}-what-is-it-{arc}", f"What Is It? ({arc})", f"mh_{n}.html", body)
    return folder


def selected_keys(novel_dir):
    with NovelStore.open(novel_dir) as store:
        return [s.key for s in store.selection()]


def test_import_wns_numbers(wns, tmp_path, clock):
    report = import_novel(tmp_path / "golden", WnsImporter(golden_core(wns).write()), clock)
    assert report.created and report.inserted == 4 and not report.failed
    assert selected_keys(tmp_path / "golden") == [ChapterKey(1), ChapterKey(2), ChapterKey(3)]
    with NovelStore.open(tmp_path / "golden") as store:
        assert store.meta.title == "My Golden Core"
        [source] = store.sources()
        assert (source.spec.backend, source.spec.url) == ("import:wns", GOLDEN)
        assert [n.title for n in store.check().unmapped] == ["Extra 1: The game has just begun"]
        version = store.read_version(store.selection()[0].version_id)
    assert [b.text for b in version.blocks] == ["Text of Chapter 1: Name 1."]  # the title echo is gone


def test_import_wns_skydemon_slugs_and_locked_chapters(wns, tmp_path, clock):
    report = import_novel(tmp_path / "mh", WnsImporter(mount_hua(wns).write()), clock)
    # "(1)"/"(2)" number arcs here: each chapter has its own slug number, so no parts.
    assert selected_keys(tmp_path / "mh") == [ChapterKey(3), ChapterKey(4)]
    assert report.unavailable == ("/projects/3801994495-return-of-the-mount-hua-sect/1-what-the-hell-1",
                                  "/projects/3801994495-return-of-the-mount-hua-sect/2-what-the-hell-2")  # fmt: skip
    with NovelStore.open(tmp_path / "mh") as store:
        check = store.check()
    assert check.gaps == (1, 2) and check.failed == ()  # locked chapters are gaps, not errors


def test_align_unavailable_inside_the_book_is_a_gap(wns, tmp_path, clock):
    folder = wns("Longevity", GOLDEN)
    folder.chapter(f"{GOLDEN}/chapter-1", "Chapter 1", "a.html")
    folder.chapter(f"{GOLDEN}/chapter-2", None, None)
    folder.chapter(f"{GOLDEN}/chapter-3", "Chapter 3", "c.html")
    import_novel(tmp_path / "n", WnsImporter(folder.write()), clock)
    with NovelStore.open(tmp_path / "n") as store:
        assert store.check().gaps == (2,)


def test_import_ccg_novelhi_pages_not_listed_are_skipped(wns, tmp_path, clock):
    folder = golden_core(wns)
    for n in range(72):
        folder.save(f"Cultivation-Chat-Group_{n}_novelhi.html", "<p>NovelHi page</p>")
    report = import_novel(tmp_path / "golden", WnsImporter(folder.write()), clock)
    assert report.inserted == 4
    assert any(note.startswith("72 saved pages not listed in main.json") for note in report.notes)


def test_titles_are_repaired_and_replacement_chars_flagged(wns, tmp_path, clock):
    folder = wns("CCG", GOLDEN)
    folder.chapter(f"{GOLDEN}/chapter-1", "Chapter 1 : Mt. Yellow�s Group", "a.html")
    folder.chapter(f"{GOLDEN}/chapter-2", "Chapter 2: Itâ€™s mojibake", "b.html")
    report = import_novel(tmp_path / "n", WnsImporter(folder.write()), clock)
    with NovelStore.open(tmp_path / "n") as store:
        titles = [s.title for s in store.selection()]
    assert titles == ["Chapter 1 : Mt. Yellow�s Group", "Chapter 2: It’s mojibake"]
    assert "1 titles contain U+FFFD (a character lost before download)" in report.notes


def test_reimport_is_unchanged_and_snapshot_is_frozen(wns, tmp_path, clock):
    folder = golden_core(wns)
    importer_dir = folder.write()
    first = import_novel(tmp_path / "golden", WnsImporter(importer_dir), clock)
    snapshot = tmp_path / "golden" / "imports" / str(first.source_id) / SNAPSHOT_NAME
    frozen = snapshot.read_bytes()

    folder.chapter(f"{GOLDEN}/chapter-4-new", "Chapter 4: New", "my-golden-core_4.html").write()
    second = import_novel(tmp_path / "golden", WnsImporter(importer_dir), clock)
    assert not second.created
    assert (second.inserted, second.unchanged) == (1, 4)
    assert second.index.added == (f"{GOLDEN.removeprefix('https://novelbin.me')}/chapter-4-new",)
    assert snapshot.read_bytes() == frozen  # legacy positions keep resolving against the first snapshot
    assert len(json.loads(next(p for p in snapshot.parent.iterdir() if p != snapshot).read_text())["chapters"]) == 5


def test_missing_page_fails_that_chapter_only(wns, tmp_path, clock):
    folder = golden_core(wns)
    root = folder.write()
    (folder.chapters_dir / "my-golden-core_00000002.html").unlink()
    report = import_novel(tmp_path / "golden", WnsImporter(root), clock)
    assert report.inserted == 3
    [(ref, reason)] = report.failed
    assert ref.endswith("chapter-2-name-2") and "my-golden-core_00000002.html" in reason
    with NovelStore.open(tmp_path / "golden") as store:
        [failed] = store.check().failed
    assert failed.item_ref == ref
